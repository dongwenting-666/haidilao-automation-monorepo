"""SealSuite VPN connection middleware — Windows implementation.

Uses pywinauto (UIA backend) to interact with the SealSuite Electron window
and winreg to locate the CorpLink executable.
"""

import logging
import os
import re
import subprocess
import time
import winreg
from pathlib import Path

import pywinauto

from vpn.errors import (
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    VPNAppNotFoundError,
    VPNConnectionError,
)

log = logging.getLogger(__name__)

SEALSUITE_TITLE = "SealSuite"


# ---------------------------------------------------------------------------
# Locate executable
# ---------------------------------------------------------------------------

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CorpLink"


def _find_exe() -> Path:
    # 1. Environment variable override
    env_path = os.environ.get("SEALSUITE_EXE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. Windows registry (most reliable — set by the installer)
    for value_name in ("DisplayIcon", "InstallLocation"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_KEY) as key:
                raw = winreg.QueryValueEx(key, value_name)[0]
                if value_name == "InstallLocation":
                    p = Path(raw) / "current" / "Client" / "CorpLink.exe"
                else:
                    p = Path(raw)
                if p.exists():
                    return p
        except OSError:
            pass

    raise VPNAppNotFoundError(
        "CorpLink/SealSuite not found in registry. "
        "Set SEALSUITE_EXE environment variable to the executable path."
    )


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def _find_window():
    """Return the SealSuite window wrapper, or *None*."""
    try:
        desktop = pywinauto.Desktop(backend="uia")
        w = desktop.window(title=SEALSUITE_TITLE)
        w.wrapper_object()
        return w
    except Exception:
        return None


def _wait_for_window() -> pywinauto.WindowSpecification:
    """Block until the SealSuite window appears."""
    for _ in range(MAX_POLL_ATTEMPTS):
        w = _find_window()
        if w is not None:
            return w
        time.sleep(POLL_INTERVAL_SECONDS)
    raise VPNAppNotFoundError("SealSuite window did not appear")


def _ensure_accessibility_tree(window):
    """Electron only exposes the a11y tree after receiving focus once."""
    try:
        window.child_window(control_type="Document").wrapper_object()
    except Exception:
        window.set_focus()
        time.sleep(1)


# ---------------------------------------------------------------------------
# VPN state
# ---------------------------------------------------------------------------

def _get_button(window):
    """Return *(button, is_connected)* or *(None, None)*."""
    _ensure_accessibility_tree(window)

    try:
        doc = window.child_window(control_type="Document")
    except Exception:
        return None, None

    for title, connected in (("On On", True), ("Off Off", False)):
        try:
            btn = doc.child_window(title=title, control_type="Button")
            btn.wrapper_object()
            return btn, connected
        except Exception:
            pass

    return None, None


def _get_connected_hours(window) -> float | None:
    """Read the elapsed-time counter above the *Time connected* label."""
    try:
        _ensure_accessibility_tree(window)
        doc = window.child_window(control_type="Document")
        label = doc.child_window(title="Time connected", control_type="Text")
        label_rect = label.rectangle()

        for child in doc.children(control_type="Text"):
            r = child.rectangle()
            if (
                r.bottom <= label_rect.top + 5
                and r.left < label_rect.right
                and r.right > label_rect.left
            ):
                m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", child.window_text())
                if m:
                    return int(m[1]) + int(m[2]) / 60 + int(m[3]) / 3600
    except Exception:
        pass
    return None


def _poll_state(expected: bool) -> bool:
    """Poll until the VPN reaches *expected* connected state."""
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        w = _find_window()
        if w is None:
            continue
        _, connected = _get_button(w)
        if connected == expected:
            return True
    return False


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

def _turn_on(window):
    btn, connected = _get_button(window)
    if btn is None:
        raise VPNConnectionError("Cannot find VPN toggle button")
    if connected:
        return  # already on
    log.info("Turning VPN on...")
    btn.invoke()
    if not _poll_state(expected=True):
        raise VPNConnectionError("VPN failed to connect")
    log.info("VPN connected")


def _cycle(window):
    """Turn VPN off then on to reset the session timer."""
    btn, connected = _get_button(window)
    if btn is None:
        raise VPNConnectionError("Cannot find VPN toggle button")
    if connected:
        log.info("Disconnecting VPN to reset session...")
        btn.invoke()
        if not _poll_state(expected=False):
            raise VPNConnectionError("VPN failed to disconnect")

    window = _find_window()
    if window is None:
        raise VPNConnectionError("Lost SealSuite window after disconnect")
    _turn_on(window)


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
        SealSuite is not installed or the window did not appear.
    VPNConnectionError
        VPN could not be toggled on.
    """
    # 1. Is SealSuite running?
    window = _find_window()
    if window is None:
        log.info("SealSuite not running, launching...")
        exe = _find_exe()
        subprocess.Popen(
            [str(exe)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        window = _wait_for_window()

    # 2. Check VPN state
    btn, connected = _get_button(window)
    if btn is None:
        raise VPNConnectionError("Cannot find VPN toggle button")

    if not connected:
        _turn_on(window)
        return

    # 3. Connected — check session age
    hours = _get_connected_hours(window)
    if hours is not None:
        log.info("VPN connected for %.1f hours", hours)
        if hours >= max_connected_hours:
            log.info(
                "Session older than %.1f hours, cycling to reset...",
                max_connected_hours,
            )
            _cycle(window)
            return
        log.info("Session healthy, no action needed")
    else:
        log.info("VPN is on (could not read timer)")
