"""SealSuite VPN connection middleware — macOS implementation.

Status detection
----------------
Reads the world-readable CorpLink log file at
``/usr/local/corplink/logs/corplink.log`` — no special permissions required.

VPN toggling
------------
Uses **cliclick** (``brew install cliclick``) to send hardware-level mouse
clicks to the CorpLink Electron app.

Why cliclick?
    • CGEvent / kCGHIDEventTap without a proper ``CGEventSource`` is silently
      ignored by Electron's renderer process.
    • AppleScript ``click`` on ``AXGroup``/``AXButton`` is unreliable in
      Electron (the button element is not exposed via Accessibility API).
    • ``cliclick`` creates events with ``kCGEventSourceStateHIDSystemState``,
      which Electron's renderer correctly processes.

Which element to click?
-----------------------
CorpLink has two VPN controls:

1. **Network tab Connect button** — large circular button on the Network/VPN page.
   This button has non-deterministic initialization time (observed 3–40 s after
   the tab mounts before it becomes interactive).  Unreliable for automation.

2. **Overview tab VPN Connectivity toggle** — small toggle on the Overview/dashboard
   page.  This toggle is immediately interactive on fresh app launch and responds
   reliably from Python subprocess.  **This is what we use.**

Reliability strategy
--------------------
1. Quit CorpLink if already running (ensures clean, predictable Overview tab state).
2. Launch a fresh instance.
3. Wait for it to settle (~6 s for login + API calls).
4. Click the Overview VPN Connectivity toggle (immediately responsive).
5. Poll until connected.
6. Hide the CorpLink window (do NOT quit — quitting sends ClientClose to
   corplink-service which tears down the WireGuard tunnel).

Calibrated offsets (window normalized to AppleScript position 100,100,
CorpLink v3.1.21, measured on fresh launch):
    Overview VPN toggle (connect) →  dx=400, dy=115
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

# Patterns matched against CorpLink log lines (local-time, no tz suffix).
_RE_DISCONNECTED = re.compile(r"vpn\.go:\d+: VPN Disconnected")
# Match either the reportVpnStatus line (steady-state) or WireGuard handshake
# complete (fires first, within a second of tunnel coming up).
_RE_CONNECTED = re.compile(
    r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"
    r".*(?:"
    r"reportVpnStatus start map\[ip:(\d+\.\d+\.\d+\.\d+)"
    r"|WireGuard Connected"
    r")"
)

# Seconds to wait after launching CorpLink before the UI is ready to click.
_LAUNCH_SETTLE_SECONDS = 6.0


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

def _find_app() -> Path:
    """Return the CorpLink app path, checking SEALSUITE_EXE override first."""
    env_path = os.environ.get("SEALSUITE_EXE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    if CORPLINK_APP.exists():
        return CORPLINK_APP
    raise VPNAppNotFoundError(
        "CorpLink.app not found at /Applications/CorpLink.app. "
        "Set SEALSUITE_EXE to override the app path."
    )


def _get_corplink_pid() -> int | None:
    """Return the PID of the main CorpLink process, or None if not running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "CorpLink"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[0]
            return int(line)
    except Exception:
        pass
    return None


def _is_running() -> bool:
    """Return True if the main CorpLink process is running."""
    return _get_corplink_pid() is not None


def _quit_app() -> None:
    """Gracefully quit CorpLink and wait for it to exit."""
    if not _is_running():
        return
    log.info("Quitting CorpLink for a clean restart...")
    subprocess.run(
        ["osascript", "-e", 'quit app "CorpLink"'],
        capture_output=True, timeout=10,
    )
    # Wait up to 10 s for the process to disappear.
    for _ in range(20):
        time.sleep(0.5)
        if not _is_running():
            log.debug("CorpLink exited cleanly")
            return
    # Force-kill if it didn't quit.
    pid = _get_corplink_pid()
    if pid:
        log.warning("CorpLink did not quit gracefully — force-killing pid %d", pid)
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)
        time.sleep(1.0)


def _launch_fresh() -> None:
    """Quit any running CorpLink instance, launch a fresh one, and wait for it to settle."""
    _quit_app()
    log.info("Launching fresh CorpLink instance...")
    app_path = _find_app()
    subprocess.Popen(
        ["open", "-a", str(app_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the process to appear.
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        if _is_running():
            break
    else:
        raise VPNAppNotFoundError("CorpLink process did not appear after launch")
    # Give the UI additional time to fully render before we start clicking.
    log.info("Waiting %.1f s for CorpLink UI to settle...", _LAUNCH_SETTLE_SECONDS)
    time.sleep(_LAUNCH_SETTLE_SECONDS)


# ---------------------------------------------------------------------------
# Log-based VPN status — no special permissions required
# ---------------------------------------------------------------------------

def _parse_log_status() -> tuple[bool, datetime | None]:
    """Parse the CorpLink log for the most recent VPN connect/disconnect event.

    Returns
    -------
    (is_connected, connected_since)
        *is_connected* — True if the last event was a connection.
        *connected_since* — naive local datetime of that event, or None.
    """
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
                        try:
                            ts = datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S")
                        except ValueError:
                            ts = None
                        return True, ts
    except OSError as e:
        log.debug("Failed to read CorpLink log: %s", e)

    return False, None


def _is_connected() -> bool:
    """Return True if VPN is currently connected (log-based)."""
    connected, _ = _parse_log_status()
    return connected


def _get_connected_hours() -> float | None:
    """Return how many hours the current VPN session has been up, or None."""
    connected, connected_since = _parse_log_status()
    if not connected or connected_since is None:
        return None
    return (datetime.now() - connected_since).total_seconds() / 3600


# ---------------------------------------------------------------------------
# VPN connect via cliclick on a freshly launched CorpLink instance
# ---------------------------------------------------------------------------

# Window is normalized to this position before clicking so offsets are stable.
_NORM_X = 100
_NORM_Y = 100
_NORM_W = 900
_NORM_H = 560

# Button offsets from AppleScript window origin, calibrated on a fresh CorpLink
# launch at window position (100,100), CorpLink v3.1.21.
#
# We use the Overview tab VPN Connectivity toggle — it is immediately interactive
# after launch (no waiting for React state initialization).
_OVERVIEW_TOGGLE_DX = 400  # Overview tab VPN Connectivity toggle
_OVERVIEW_TOGGLE_DY = 115

_NORMALIZE_SCRIPT = f"""\
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
        set position of window 1 to {{{_NORM_X}, {_NORM_Y}}}
        set size of window 1 to {{{_NORM_W}, {_NORM_H}}}
        delay 0.3
        set {{wx, wy}} to position of window 1
        set {{ww, wh}} to size of window 1
        return (wx as string) & "," & (wy as string) & "," & (ww as string) & "," & (wh as string)
    end tell
end tell
"""


def _cliclick(*args: str) -> None:
    """Invoke cliclick with the given arguments.

    Raises
    ------
    VPNConnectionError
        If cliclick is not installed, times out, or exits non-zero.
    """
    try:
        result = subprocess.run(
            ["cliclick"] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise VPNConnectionError(f"cliclick failed: {result.stderr.strip()}")
    except FileNotFoundError:
        raise VPNConnectionError(
            "cliclick not found — install with: brew install cliclick"
        )
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("cliclick timed out")


def _activate() -> None:
    """Bring CorpLink to the foreground."""
    subprocess.run(
        ["osascript", "-e", 'tell application "CorpLink" to activate'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.4)


def _normalize_window() -> tuple[int, int, int, int]:
    """Activate CorpLink and normalize its window. Returns (wx, wy, ww, wh)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _NORMALIZE_SCRIPT],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise VPNConnectionError("Timed out normalizing CorpLink window")

    output = result.stdout.strip()
    if result.returncode != 0 or output == "NO_WINDOW":
        raise VPNAppNotFoundError(
            f"CorpLink window not found: {result.stderr.strip() or output}"
        )
    try:
        return tuple(int(v) for v in output.split(","))  # type: ignore[return-value]
    except (ValueError, TypeError):
        raise VPNConnectionError(f"Unexpected window geometry: {output!r}")


def _connect_vpn() -> None:
    """Click the Overview VPN Connectivity toggle to initiate a connection.

    The Overview toggle is immediately interactive after a fresh CorpLink
    launch — no waiting for React state initialization required.

    Raises VPNConnectionError / VPNAppNotFoundError on failure.
    """
    wx, wy, ww, wh = _normalize_window()

    toggle_x = wx + _OVERVIEW_TOGGLE_DX
    toggle_y = wy + _OVERVIEW_TOGGLE_DY

    log.debug(
        "Window AS(%d,%d) %dx%d → overview-toggle(%d,%d)",
        wx, wy, ww, wh, toggle_x, toggle_y,
    )

    _activate()
    # Move to toggle first (triggers hover), then click.
    _cliclick(f"m:{toggle_x},{toggle_y}")
    time.sleep(0.3)
    _cliclick(f"c:{toggle_x},{toggle_y}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_vpn(*, max_connected_hours: float = 6.0) -> None:
    """Ensure CorpLink VPN is connected and has enough session time remaining.

    Call this at the start of any automation that needs access to Haidilao
    internal resources.  The function returns immediately if the VPN is
    already healthy; otherwise it quits CorpLink, launches a fresh instance,
    clicks Connect, and waits for the tunnel to come up.

    Parameters
    ----------
    max_connected_hours:
        If the current session has been up longer than this, it is cycled
        (quit → relaunch → reconnect) to avoid the server-side 7.5-hour hard
        limit mid-automation.  Default is 6.0 h, leaving a 1.5-hour buffer.

    Raises
    ------
    VPNAppNotFoundError
        CorpLink is not installed or failed to start.
    VPNConnectionError
        VPN could not be connected.  Check that ``cliclick`` is installed
        (``brew install cliclick``) and that this process has Accessibility
        permission in System Settings › Privacy & Security › Accessibility.
    """
    # Check if VPN is already up and healthy.
    if _is_connected():
        hours = _get_connected_hours()
        if hours is not None:
            log.info("VPN connected for %.1f hours", hours)
            if hours < max_connected_hours:
                log.info("Session healthy — no action needed")
                return
            log.info("Session ≥ %.1f h — reconnecting to reset timer...", max_connected_hours)
        else:
            log.info("VPN is on (session age unknown) — no action needed")
            return

    # VPN is down or session is stale — do a fresh launch and connect.
    log.info("VPN not connected (or session stale) — launching fresh CorpLink...")
    _launch_fresh()

    # Click Connect.
    _connect_vpn()

    # Poll until connected.
    log.info("Waiting for VPN to connect...")
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        if _is_connected():
            log.info("VPN connected ✓")
            # Hide the window — do NOT quit. Quitting CorpLink sends ClientClose
            # to corplink-service which tears down the WireGuard tunnel.
            # The app keeps the tunnel alive as long as it's running.
            subprocess.run(
                ["osascript", "-e", 'tell application "CorpLink" to activate'],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to tell process "CorpLink" '
                 'to set visible to false'],
                capture_output=True, timeout=5,
            )
            return

    raise VPNConnectionError(
        "VPN did not connect within the polling window after clicking Connect"
    )
