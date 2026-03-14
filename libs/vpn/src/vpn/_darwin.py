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
# AppleScript GUI automation (needs Accessibility permission)
# ---------------------------------------------------------------------------

_APPLESCRIPT_FIND_AND_CLICK_TOGGLE = """\
tell application "System Events"
    if not (exists process "CorpLink") then
        return "NOT_RUNNING"
    end if

    tell process "CorpLink"
        set frontmost to true
        delay 0.5

        -- The VPN toggle is deeply nested inside the Electron web area.
        -- Use "entire contents" to flatten the tree and find it reliably.
        tell window 1
            set webArea to UI element 1
            set allElements to entire contents of webArea
            repeat with elem in allElements
                if role of elem is "AXCheckBox" then
                    set t to title of elem
                    if t is "Off Off" or t is "On On" then
                        click elem
                        return "CLICKED"
                    end if
                end if
            end repeat
        end tell
    end tell
    return "NOT_FOUND"
end tell
"""

_APPLESCRIPT_GET_VPN_STATE = """\
tell application "System Events"
    if not (exists process "CorpLink") then
        return "NOT_RUNNING"
    end if

    tell process "CorpLink"
        tell window 1
            set webArea to UI element 1
            set allElements to entire contents of webArea
            repeat with elem in allElements
                if role of elem is "AXCheckBox" then
                    set t to title of elem
                    if t is "On On" then
                        return "ON"
                    else if t is "Off Off" then
                        return "OFF"
                    end if
                end if
            end repeat
        end tell
    end tell
    return "UNKNOWN"
end tell
"""


def _run_applescript(script: str, *, timeout: int = 15) -> str:
    """Run an AppleScript and return its stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not allowed assistive access" in stderr.lower():
                raise VPNConnectionError(
                    "Accessibility permission required. "
                    "Add your terminal app to: System Settings > "
                    "Privacy & Security > Accessibility"
                )
            raise VPNConnectionError(f"AppleScript failed: {stderr}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("AppleScript timed out")


def _get_gui_state() -> bool | None:
    """Read VPN state from the CorpLink GUI (needs Accessibility permission).

    Returns True (on), False (off), or None (could not determine).
    """
    try:
        result = _run_applescript(_APPLESCRIPT_GET_VPN_STATE)
        if result == "ON":
            return True
        if result == "OFF":
            return False
    except VPNConnectionError:
        pass
    return None


def _toggle_vpn() -> None:
    """Click the VPN toggle in the CorpLink window via AppleScript."""
    result = _run_applescript(_APPLESCRIPT_FIND_AND_CLICK_TOGGLE, timeout=30)

    if result == "NOT_RUNNING":
        raise VPNAppNotFoundError("CorpLink is not running")
    if result == "NOT_FOUND":
        raise VPNConnectionError(
            "Could not find VPN toggle in CorpLink window. "
            "The UI may have changed — check the CorpLink window manually."
        )
    # result == "CLICKED" — success


def _poll_state(expected: bool) -> bool:
    """Poll until VPN reaches the expected state (GUI first, log fallback)."""
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        # GUI state updates immediately; prefer it
        gui = _get_gui_state()
        if gui == expected:
            return True
        # GUI unavailable (window closed, no permission) — fall back to log
        if gui is None and _is_connected() == expected:
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
