"""SealSuite VPN connection middleware — macOS implementation.

Status detection uses the world-readable CorpLink log file at
``/usr/local/corplink/logs/corplink.log`` (no permissions needed).

VPN toggling uses cliclick to send hardware-level mouse clicks to the
CorpLink Electron app's Connect/Disconnect button.

Why cliclick:
- CGEvent posted via kCGHIDEventTap without a proper CGEventSource is ignored
  by Electron's renderer process.
- AppleScript `click` on AXGroup/AXButton elements is unreliable in Electron.
- cliclick uses the correct CGEventSource internally, which Electron accepts.

Install: brew install cliclick
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


def _get_corplink_pid() -> int | None:
    """Return the PID of the main CorpLink process, or None if not running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "CorpLink"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def _is_running() -> bool:
    """Check if CorpLink process is running."""
    return _get_corplink_pid() is not None


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
    """Parse CorpLink log for the latest VPN event."""
    if not CORPLINK_LOG.exists():
        log.debug("CorpLink log not found at %s", CORPLINK_LOG)
        return False, None

    try:
        with open(CORPLINK_LOG, "rb") as f:
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

                if remaining > 0:
                    carry = lines[0].encode("utf-8", errors="replace")
                    scan_lines = lines[1:]
                else:
                    scan_lines = lines

                for line in reversed(scan_lines):
                    if _RE_DISCONNECTED.search(line):
                        return False, None

                    m = _RE_CONNECTED.search(line)
                    if m:
                        ts_str = m.group(1)
                        try:
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

    elapsed = datetime.now() - connected_since
    return elapsed.total_seconds() / 3600


# ---------------------------------------------------------------------------
# VPN toggle — robust against minimized/off-screen/resized windows.
#
# Strategy:
#   1. Ensure CorpLink is running; launch if not.
#   2. AppleScript: hide all other apps, activate CorpLink, unminimize,
#      normalize window to a known position and size.
#   3. cliclick: click the Connect/Disconnect button at calibrated coords.
#
# Button coordinates (calibrated, CorpLink v3.1.21, window at AppleScript
# position 200,200 with size 888×560):
#   The Connect button is at screen (680, 340), i.e. offset (480, 140) from
#   the AppleScript-reported window origin. The 52px title bar gap between
#   AppleScript position and actual render position is accounted for here.
#
# Why cliclick works:
#   cliclick uses CGEventCreateMouseEvent with a CGEventSource (HIDSystemState),
#   which Electron's input event handling accepts. Plain CGEvent without a
#   proper source, or AppleScript synthetic clicks, are ignored by Electron.
# ---------------------------------------------------------------------------

# Fixed window placement — move here before clicking so coords are stable.
_NORM_POS = (200, 200)
_NORM_SIZE = (900, 600)  # macOS will constrain slightly; use returned geometry

# Connect button offset from AppleScript-reported window position (200, 200).
# Empirically calibrated by scanning a 20-point grid — (680, 340) triggered
# jsonRequest-connectVpn in the Electron debug log.
_BTN_WIN_X = 480   # screen_x - as_window_x
_BTN_WIN_Y = 140   # screen_y - as_window_y

_PREPARE_SCRIPT = """\
tell application "System Events"
    set visApps to every application process whose visible is true and name is not "CorpLink" and name is not "Finder"
    repeat with a in visApps
        try
            set visible of a to false
        end try
    end repeat
end tell
tell application "CorpLink" to activate
delay 0.3
tell application "System Events"
    tell process "CorpLink"
        try
            if miniaturized of window 1 then set miniaturized of window 1 to false
            delay 0.1
        end try
        if not (exists window 1) then
            return "NO_WINDOW"
        end if
        set position of window 1 to {200, 200}
        set size of window 1 to {900, 600}
        delay 0.4
        set {wx, wy} to position of window 1
        set {ww, wh} to size of window 1
        return (wx as string) & "," & (wy as string) & "," & (ww as string) & "," & (wh as string)
    end tell
end tell
"""

_CLICLICK = "cliclick"


def _cliclick_available() -> bool:
    try:
        return subprocess.run(
            ["which", _CLICLICK], capture_output=True, timeout=3
        ).returncode == 0
    except Exception:
        return False


def _click_vpn_button() -> None:
    """Hide other windows, normalize CorpLink window, then click VPN button via cliclick."""
    if not _cliclick_available():
        raise VPNConnectionError(
            "cliclick not found. Install with: brew install cliclick"
        )

    # Step 1: Normalize window position via AppleScript
    try:
        result = subprocess.run(
            ["osascript", "-e", _PREPARE_SCRIPT],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("Timed out activating CorpLink window")

    output = result.stdout.strip()
    if result.returncode != 0 or output == "NO_WINDOW":
        raise VPNAppNotFoundError(
            f"CorpLink window not found or AppleScript failed: {result.stderr.strip()}"
        )

    try:
        wx, wy, ww, wh = (int(v) for v in output.split(","))
    except (ValueError, TypeError):
        raise VPNConnectionError(f"Unexpected window geometry response: {output!r}")

    # Step 2: Compute button screen coordinates
    btn_x = wx + _BTN_WIN_X
    btn_y = wy + _BTN_WIN_Y

    log.debug("Clicking VPN button at screen (%d, %d) [window at (%d,%d) size %dx%d]",
              btn_x, btn_y, wx, wy, ww, wh)

    # Step 3: Re-activate right before clicking
    subprocess.run(
        ["osascript", "-e", 'tell application "CorpLink" to activate'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.5)

    # Step 4: Hardware click via cliclick
    try:
        subprocess.run(
            [_CLICLICK, f"c:{btn_x},{btn_y}"],
            capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("cliclick timed out")

    time.sleep(0.3)


# ---------------------------------------------------------------------------
# Toggle helpers
# ---------------------------------------------------------------------------

def _toggle_vpn() -> None:
    """Click the CorpLink VPN Connect/Disconnect button."""
    _click_vpn_button()


def _poll_state(expected: bool, initial_delay: float = 5.0) -> bool:
    """Poll until VPN reaches the expected state (log-based)."""
    time.sleep(initial_delay)
    for _ in range(MAX_POLL_ATTEMPTS):
        if _is_connected() == expected:
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


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
    """Ensure VPN is connected with enough session time remaining."""
    # 1. Is CorpLink running?
    if not _is_running():
        log.info("CorpLink not running, launching...")
        app = _find_app()
        _launch_app(app)
        for _ in range(MAX_POLL_ATTEMPTS):
            time.sleep(POLL_INTERVAL_SECONDS)
            if _is_running():
                break
        else:
            raise VPNAppNotFoundError("CorpLink did not start")

    # 2. Check VPN state
    connected = _is_connected()

    if not connected:
        _turn_on()
        return

    # 3. Connected — check session age
    hours = _get_connected_hours()
    if hours is not None:
        log.info("VPN connected for %.1f hours", hours)
        if hours >= max_connected_hours:
            log.info("Session older than %.1f hours, cycling to reset...", max_connected_hours)
            _cycle()
            return
        log.info("Session healthy, no action needed")
    else:
        log.info("VPN is on (could not determine session age)")
