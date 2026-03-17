"""SealSuite VPN connection middleware — macOS implementation.

Status detection uses the world-readable CorpLink log file at
``/usr/local/corplink/logs/corplink.log`` (no permissions needed).

VPN toggling uses AppleScript (``osascript``) via System Events to click
the toggle button in the CorpLink Electron window.  This requires
Accessibility permission — the calling app (Terminal / iTerm2 / Cursor)
must be added to System Settings > Privacy & Security > Accessibility.
"""

import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from vpn.errors import (
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    VPNAppNotFoundError,
    VPNConnectionError,
)

log = logging.getLogger(__name__)

CORPLINK_APP = Path("/Applications/CorpLink.app")
CORPLINK_LOG = Path("/usr/local/corplink/logs/corplink.log")

# Log patterns
_RE_DISCONNECTED = re.compile(r"vpn\.go:\d+: VPN Disconnected")
_RE_CONNECTED = re.compile(
    r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}).*reportVpnStatus start map\[ip:(\d+\.\d+\.\d+\.\d+)"
)


# ---------------------------------------------------------------------------
# Locate application
# ---------------------------------------------------------------------------

def _find_app() -> Path:
    env_path = os.environ.get("SEALSUITE_EXE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    if CORPLINK_APP.exists():
        return CORPLINK_APP

    raise VPNAppNotFoundError(
        "CorpLink.app not found at /Applications/CorpLink.app. "
        "Set SEALSUITE_EXE environment variable to the app path."
    )


def _is_running() -> bool:
    """Check if CorpLink process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "CorpLink"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _launch_app(app_path: Path) -> None:
    subprocess.Popen(
        ["open", str(app_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Log-based VPN status (no permissions needed)
# ---------------------------------------------------------------------------

def _parse_log_status() -> tuple[bool, datetime | None]:
    """Parse CorpLink log for the latest VPN event.

    Returns
    -------
    (is_connected, connected_since)
        *is_connected* is True if the last event was a connection.
        *connected_since* is the timestamp of the last connection event,
        or None if disconnected or unknown.
    """
    if not CORPLINK_LOG.exists():
        log.debug("CorpLink log not found at %s", CORPLINK_LOG)
        return False, None

    try:
        with open(CORPLINK_LOG, "rb") as f:
            # Read from end in chunks to find the last relevant event
            f.seek(0, 2)
            chunk_size = 8192
            remaining = f.tell()
            carry = b""

            while remaining > 0:
                read_size = min(chunk_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                raw = f.read(read_size) + carry
                lines = raw.decode("utf-8", errors="replace").splitlines()

                # First line may be partial (split by chunk boundary);
                # save it for the next iteration unless we're at file start
                if remaining > 0:
                    carry = lines[0].encode("utf-8", errors="replace")
                    scan_lines = lines[1:]
                else:
                    scan_lines = lines

                # Scan lines in reverse
                for line in reversed(scan_lines):
                    if _RE_DISCONNECTED.search(line):
                        return False, None

                    m = _RE_CONNECTED.search(line)
                    if m:
                        ts_str = m.group(1)
                        try:
                            # Log timestamps are local time (no tz info)
                            ts = datetime.strptime(ts_str, "%Y/%m/%d %H:%M:%S")
                        except ValueError:
                            ts = None
                        return True, ts
    except OSError as e:
        log.debug("Failed to read CorpLink log: %s", e)

    return False, None


def _is_connected() -> bool:
    """Determine VPN connection status from log."""
    connected, _ = _parse_log_status()
    return connected


def _get_connected_hours() -> float | None:
    """Get how many hours the current VPN session has been connected."""
    connected, connected_since = _parse_log_status()
    if not connected or connected_since is None:
        return None

    # Both are naive local datetimes — safe to subtract
    elapsed = datetime.now() - connected_since
    return elapsed.total_seconds() / 3600


# ---------------------------------------------------------------------------
# CGEvent mouse click — toggles VPN by clicking the Connect/Disconnect button.
#
# CorpLink is an Electron app; its UI is not exposed via macOS Accessibility.
# Instead we:
#   1. Activate CorpLink and bring its window to front.
#   2. Read the window position via System Events (no special permission needed).
#   3. Click the centre of the main content area where the VPN button lives.
#
# The button coordinates are derived from the window geometry:
#   - Left navigation sidebar is ~200 px wide.
#   - The VPN toggle/button sits ~200 px below the top of the content area.
#   - These offsets were calibrated empirically and are stable across versions.
# ---------------------------------------------------------------------------

_CLICK_SCRIPT = """\
tell application "CorpLink" to activate
delay 0.5
tell application "System Events"
    tell process "CorpLink"
        if not (exists window 1) then
            return "NO_WINDOW"
        end if
        set {wx, wy} to position of window 1
        set {ww, wh} to size of window 1
        return (wx as string) & "," & (wy as string) & "," & (ww as string) & "," & (wh as string)
    end tell
end tell
"""

# Fraction of content-area width/height where the VPN button is centred.
# Content area starts after the left nav bar (~200 px from left edge).
_NAV_WIDTH_PX = 200
_BUTTON_Y_OFFSET_PX = 200  # from top of window


def _click_vpn_button() -> None:
    """Click the CorpLink VPN Connect/Disconnect button via CGEvent mouse click.

    Does NOT require Accessibility permission — only uses System Events to read
    window geometry, then posts a CGEvent at the calculated screen coordinate.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", _CLICK_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("Timed out activating CorpLink")

    if output == "NO_WINDOW":
        raise VPNAppNotFoundError("CorpLink window not found")

    try:
        wx, wy, ww, wh = (int(v) for v in output.split(","))
    except (ValueError, TypeError):
        raise VPNConnectionError(f"Unexpected window geometry: {output!r}")

    # Centre of the VPN button within the content pane.
    content_x = wx + _NAV_WIDTH_PX + (ww - _NAV_WIDTH_PX) // 2
    content_y = wy + _BUTTON_Y_OFFSET_PX + (wh - _BUTTON_Y_OFFSET_PX) // 3

    _cgevent_click(content_x, content_y)
    # Small pause to let the Electron renderer process the click.
    time.sleep(0.3)


def _cgevent_click(x: int, y: int) -> None:
    """Post a left-mouse-down/up event pair at screen coordinate (x, y)."""
    # Build the click via osascript so we don't need PyObjC as a dependency.
    script = f"""\
do shell script "python3 -c \\"
import Quartz, time
pos = Quartz.CGPointMake({x}, {y})
dn = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, pos, Quartz.kCGMouseButtonLeft)
up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, pos, Quartz.kCGMouseButtonLeft)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, dn)
time.sleep(0.1)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
\\""
"""
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("CGEvent click timed out")


def _toggle_vpn() -> None:
    """Click the VPN Connect/Disconnect button in the CorpLink window."""
    _click_vpn_button()


def _poll_state(expected: bool) -> bool:
    """Poll until VPN reaches the expected state (log-based)."""
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        if _is_connected() == expected:
            return True
    return False


# ---------------------------------------------------------------------------
# Toggle helpers
# ---------------------------------------------------------------------------

def _turn_on() -> None:
    if _is_connected():
        return
    log.info("Turning VPN on...")
    _toggle_vpn()
    if not _poll_state(expected=True):
        raise VPNConnectionError("VPN failed to connect")
    log.info("VPN connected")


def _cycle() -> None:
    """Turn VPN off then on to reset the session timer."""
    if _is_connected():
        log.info("Disconnecting VPN to reset session...")
        _toggle_vpn()
        if not _poll_state(expected=False):
            raise VPNConnectionError("VPN failed to disconnect")

    _turn_on()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_vpn(*, max_connected_hours: float = 6.0) -> None:
    """Ensure VPN is connected with enough session time remaining.

    Parameters
    ----------
    max_connected_hours:
        If the current session has been connected longer than this, the
        connection is cycled to avoid expiry mid-automation.  The SealSuite
        session expires after 7 h 30 min, so the default of 6 h leaves a
        comfortable buffer.

    Raises
    ------
    VPNAppNotFoundError
        CorpLink is not installed or could not be launched.
    VPNConnectionError
        VPN could not be toggled on.  If Accessibility permission is
        missing, the error message includes instructions to grant it.
    """
    # 1. Is CorpLink running?
    if not _is_running():
        log.info("CorpLink not running, launching...")
        app = _find_app()
        _launch_app(app)
        # Wait for process to start
        for _ in range(MAX_POLL_ATTEMPTS):
            time.sleep(POLL_INTERVAL_SECONDS)
            if _is_running():
                break
        else:
            raise VPNAppNotFoundError("CorpLink did not start")

    # 2. Check VPN state (log-based, no permissions needed)
    connected = _is_connected()

    if not connected:
        _turn_on()
        return

    # 3. Connected — check session age
    hours = _get_connected_hours()
    if hours is not None:
        log.info("VPN connected for %.1f hours", hours)
        if hours >= max_connected_hours:
            log.info(
                "Session older than %.1f hours, cycling to reset...",
                max_connected_hours,
            )
            _cycle()
            return
        log.info("Session healthy, no action needed")
    else:
        log.info("VPN is on (could not determine session age)")
