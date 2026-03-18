"""SAP GUI for Java connection via Scripting Console bridge (macOS only).

Automates SAP GUI for Java on macOS by sending JavaScript to the
built-in Scripting Console (Scripts > Scripting Console).  The console
runs a Nashorn JS engine with full access to the SAP Scripting API.

IPC flow for each operation:
    1. Build a JS snippet that writes its result to a temp file via
       ``java.io.FileWriter``
    2. Paste the snippet into the Scripting Console input via AppleScript
    3. Click the Play button to execute
    4. Read the result file from disk

Requires Accessibility permission — add your terminal app to:
System Settings > Privacy & Security > Accessibility.
"""

from __future__ import annotations

import glob as _glob
import json
import logging
import os
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from sap_gui.errors import SAPConnectionError

log = logging.getLogger(__name__)

_LANDSCAPE_XML = Path.home() / "Library/Preferences/SAP/SAPGUILandscape.xml"


def _find_sapgui_app() -> str:
    """Locate the SAP GUI for Java application bundle.

    Checks the ``SAPGUI_APP`` environment variable first, then searches
    ``/Applications/SAPGUI *.app`` for the newest version.
    """
    env = os.environ.get("SAPGUI_APP")
    if env and os.path.isdir(env):
        return env
    matches = sorted(_glob.glob("/Applications/SAPGUI *.app"))
    if matches:
        return matches[-1]  # newest version
    return "/Applications/SAPGUI 8.10.app"  # fallback


_SAPGUI_APP = _find_sapgui_app()

# Short timeout for the first execute() attempt.  If the console is
# stale after a screen transition, this ensures fast failure so we can
# re-open and retry with the full caller timeout.
_FAST_TIMEOUT = 8.0

# JS template uses an IIFE to avoid Nashorn variable-scope collisions
# across consecutive script runs in the same Scripting Console session.
# {body} is either an expression (whose result is captured) or a void statement.
_JS_TEMPLATE = """\
(function() {{
    try {{
        var ses = application.children.elementAt(0).children.elementAt(0);
        {body}
        var fw = new java.io.FileWriter("{result_path}");
        fw.write(JSON.stringify({{ok: true, v: typeof __r === "undefined" ? null : __r == null ? null : "" + __r}}));
        fw.close();
    }} catch(e) {{
        var fw = new java.io.FileWriter("{result_path}");
        fw.write(JSON.stringify({{ok: false, e: "" + e}}));
        fw.close();
    }}
}})()
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
                raise SAPConnectionError(
                    "Accessibility permission required. "
                    "Add your terminal app to: System Settings > "
                    "Privacy & Security > Accessibility"
                )
            raise SAPConnectionError(f"AppleScript failed: {stderr}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise SAPConnectionError("AppleScript timed out")


def _is_sapgui_running() -> bool:
    """Check if SAPGUI process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "SAPGUI"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _read_landscape_connection() -> str | None:
    """Parse SAP GUI landscape XML for the first server connection string.

    Reads ``~/Library/Preferences/SAP/SAPGUILandscape.xml`` and extracts
    the ``server`` attribute (``host:port``) from the first ``<Service>``
    element, returning it in SAP connection string format ``/H/<host>/S/<port>``.
    """
    if not _LANDSCAPE_XML.exists():
        return None
    try:
        tree = ET.parse(_LANDSCAPE_XML)
        for svc in tree.iter("Service"):
            server = svc.get("server", "")
            if ":" in server:
                host, port = server.rsplit(":", 1)
                return f"/H/{host}/S/{port}"
    except Exception:
        log.debug("Failed to parse landscape XML: %s", _LANDSCAPE_XML, exc_info=True)
    return None


def _detect_connection_string() -> str | None:
    """Detect SAP connection string from environment or landscape config.

    Checks ``SAP_CONNECTION`` env var first, then falls back to the
    first entry in the SAP GUI landscape XML.
    """
    env = os.environ.get("SAP_CONNECTION")
    if env:
        return env
    return _read_landscape_connection()


# ---------------------------------------------------------------------------
# PascalCase → camelCase conversion
# ---------------------------------------------------------------------------

def _pascal_to_camel(name: str) -> str:
    """Convert PascalCase to camelCase.

    Examples:
        MessageType → messageType
        User → user
        SystemName → systemName
        Text → text
    """
    if not name or name[0].islower():
        return name
    return name[0].lower() + name[1:]


# ---------------------------------------------------------------------------
# Scripting Console bridge
# ---------------------------------------------------------------------------

class _ScriptingBridge:
    """Executes JavaScript via SAP GUI for Java's Scripting Console.

    Uses AppleScript to paste JS into the console input, clicks Play,
    then reads the result from a temp file written by the JS code.
    """

    # Minimum seconds between consecutive execute() calls.
    # Prevents clipboard/focus race conditions in the Scripting Console.
    _MIN_INTERVAL = 0.6

    def __init__(self) -> None:
        self._tmp_dir_obj = tempfile.TemporaryDirectory(prefix="sapgui_bridge_")
        self._tmp_dir = Path(self._tmp_dir_obj.name)
        self._counter = 0
        self._console_open = False
        self._last_execute = 0.0  # monotonic timestamp of last execute()

    def _next_result_path(self) -> Path:
        self._counter += 1
        return self._tmp_dir / f"result_{self._counter}.json"

    def _open_console(self) -> None:
        """Open the Scripting Console via the Scripts menu.

        The console occupies the main SAP session window.  When SAP
        popups are open, that window is no longer ``window 1``, so we
        search by name (contains *New Script*) to find it reliably.
        """
        if self._console_open:
            return

        script = """\
tell application "System Events"
    tell process "SAPGUI"
        set frontmost to true
        delay 0.3

        -- Check if console is already open (window name contains "New Script")
        repeat with w in every window
            if name of w contains "New Script" then
                -- Wait for UI to stabilize after screen transitions
                delay 0.5
                return "OK"
            end if
        end repeat

        -- Not open yet — open via menu
        click menu item "Scripting..." of menu "Scripts" of menu bar item "Scripts" of menu bar 1
    end tell
end tell
delay 2.0
-- Verify the console appeared
tell application "System Events"
    tell process "SAPGUI"
        repeat with w in every window
            if name of w contains "New Script" then
                return "OK"
            end if
        end repeat
    end tell
end tell
return "NOT_FOUND"
"""
        result = _run_applescript(script, timeout=15)
        if result != "OK":
            raise SAPConnectionError(
                "Could not open Scripting Console. "
                "Ensure SAP GUI for Java is running and connected."
            )
        self._console_open = True
        log.debug("Scripting Console opened")

    def _paste_and_run(self, js_code: str) -> None:
        """Paste JS code into the console input and click Play.

        The Scripting Console lives in a SAP window whose name contains
        ``New Script``.  When popups are open it is NOT ``window 1``,
        so we search by name every time and reference it directly by
        variable instead of positional ``window 1``.

        Element hierarchy inside the console window:
          - Input: ``text area 1 of scroll area 1 of splitter group 1``
          - Play button: button whose ``description`` is ``"Play"``
        """
        # Copy JS to clipboard, then paste into the console input field
        subprocess.run(
            ["pbcopy"],
            input=js_code.encode("utf-8"),
            check=True,
        )

        # Find the Scripting Console by name and interact with it
        # directly via the window variable (not positional window 1),
        # preventing accidental paste into SAP popups.
        script = """\
tell application "System Events"
    tell process "SAPGUI"
        set frontmost to true
        delay 0.2

        -- Find the Scripting Console window by name.
        set consoleWin to missing value
        repeat with w in every window
            if name of w contains "New Script" then
                set consoleWin to w
                exit repeat
            end if
        end repeat

        if consoleWin is missing value then
            return "NO_CONSOLE"
        end if

        -- Raise console to front and reference it directly.
        perform action "AXRaise" of consoleWin
        delay 0.3

        tell consoleWin
            -- Focus input area.  Try multiple element-type variants across
            -- SAP GUI for Java versions and macOS accessibility API changes:
            --   splitter group / split group (AXSplitGroup)
            --   text area / text field (AXTextArea vs AXTextField)
            set inputArea to missing value
            try
                set inputArea to text area 1 of scroll area 1 of splitter group 1
            end try
            if inputArea is missing value then
                try
                    set inputArea to text field 1 of scroll area 1 of splitter group 1
                end try
            end if
            if inputArea is missing value then
                try
                    set inputArea to text area 1 of scroll area 1 of UI element 1
                end try
            end if
            if inputArea is missing value then
                try
                    set inputArea to text field 1 of scroll area 1 of UI element 1
                end try
            end if
            if inputArea is missing value then
                return "NO_INPUT_AREA"
            end if
            click inputArea
            delay 0.15
            -- Select all and paste
            keystroke "a" using command down
            delay 0.1
            keystroke "v" using command down
            delay 0.3
            -- Click Play button (identified by description)
            set allButtons to every button
            repeat with btn in allButtons
                if description of btn is "Play" then
                    click btn
                    exit repeat
                end if
            end repeat
        end tell
    end tell
end tell
"""
        # Retry once on transient AppleScript errors (e.g. "Invalid index"
        # when the console window exists but hasn't fully rendered yet).
        last_err: SAPConnectionError | None = None
        for attempt in range(2):
            try:
                result = _run_applescript(script, timeout=15)
                break
            except SAPConnectionError as exc:
                if "Invalid index" in str(exc) and attempt == 0:
                    log.debug("Console UI not ready, retrying after delay...")
                    last_err = exc
                    time.sleep(1.0)
                    continue
                raise
        else:
            raise last_err  # type: ignore[misc]

        if result == "NO_CONSOLE":
            self._console_open = False
            raise SAPConnectionError(
                "Scripting Console window not found. It may have been "
                "closed by a SAP screen transition."
            )

    def execute(
        self,
        js_expression: str,
        *,
        void: bool = False,
        timeout: float = 30.0,
    ) -> str | None:
        """Execute a JS expression and return its string result.

        If the Scripting Console was closed or became unresponsive
        (e.g. after a SAP screen transition), it is automatically
        re-opened and the command is retried once.

        Args:
            js_expression: JavaScript expression/statement to execute.
            void: If True, the expression is a statement with no return value.
            timeout: Maximum seconds to wait for the result file.  SAP
                operations like ``sendVKey(8)`` (F8 / Execute) block the
                JS engine until the server responds, which can take well
                over 30 s for large reports.  Callers that trigger heavy
                SAP processing should pass a larger value.

        Returns:
            The string result, or None for null/void results.

        Raises:
            SAPConnectionError: If execution fails.
        """
        # Throttle: ensure minimum interval between calls
        elapsed = time.monotonic() - self._last_execute
        if elapsed < self._MIN_INTERVAL:
            time.sleep(self._MIN_INTERVAL - elapsed)

        return self._execute_with_retry(js_expression, void=void, timeout=timeout)

    def _execute_once(
        self,
        js_expression: str,
        *,
        void: bool,
        timeout: float,
    ) -> str | None:
        """Build JS, paste into the console, poll for result."""
        self._open_console()

        result_path = self._next_result_path()
        escaped_path = str(result_path).replace("\\", "\\\\")

        if void:
            body = f"{js_expression};"
        else:
            body = f"var __r = {js_expression};"

        js_code = _JS_TEMPLATE.format(body=body, result_path=escaped_path)

        self._paste_and_run(js_code)

        # Poll with exponential backoff: 0.2s → 0.4s → 0.8s → ... capped at 2s
        deadline = time.monotonic() + timeout
        interval = 0.2
        while time.monotonic() < deadline:
            time.sleep(interval)
            interval = min(interval * 2, 2.0)
            if result_path.exists():
                try:
                    raw = result_path.read_text(encoding="utf-8").strip()
                    if not raw:
                        continue  # file created but not yet written
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue  # partial write, retry
                # Successfully parsed — safe to delete
                result_path.unlink(missing_ok=True)
                if data.get("ok"):
                    self._last_execute = time.monotonic()
                    return data.get("v")
                else:
                    raise SAPConnectionError(
                        f"SAP JS error: {data.get('e', 'unknown error')}"
                    )

        raise SAPConnectionError(
            f"Bridge timeout ({timeout}s) — no result received"
        )

    def _execute_with_retry(
        self,
        js_expression: str,
        *,
        void: bool,
        timeout: float,
    ) -> str | None:
        """Execute with automatic retry on console loss or timeout.

        SAP screen transitions (``/n``, ``sendVKey``, etc.) can close or
        reset the Scripting Console.  When the first attempt fails — either
        because ``_paste_and_run`` cannot find the window, or because the
        result file never appears — we close the console, re-open it from
        the Scripts menu, and retry once with the full timeout.

        The first attempt uses ``_FAST_TIMEOUT`` so that a stale console
        is detected quickly — but only for short operations.  When the
        caller specifies a large timeout (> 30 s), the operation itself
        may be slow (e.g. a button press that triggers file I/O), so we
        use the full timeout to avoid killing a legitimate long-running
        SAP operation and then re-opening the console (which would
        dismiss any open dialog).
        """
        # For long-running operations, use the full timeout on the first
        # attempt — the fast-timeout retry would do more harm than good.
        first_timeout = min(_FAST_TIMEOUT, timeout) if timeout <= 30.0 else timeout

        try:
            return self._execute_once(
                js_expression, void=void, timeout=first_timeout
            )
        except SAPConnectionError:
            log.debug("Console lost or unresponsive, re-opening...")
            self.reset()
            self._open_console()
            try:
                return self._execute_once(
                    js_expression, void=void, timeout=timeout
                )
            except SAPConnectionError:
                self.reset()
                raise

    def reset(self) -> None:
        """Reset console state so the next execute() re-opens it."""
        self._console_open = False

    def _close_console_window(self) -> None:
        """Close the Scripting Console window if it is open."""
        if not self._console_open:
            return
        script = """\
tell application "System Events"
    tell process "SAPGUI"
        repeat with w in every window
            if name of w contains "New Script" then
                perform action "AXRaise" of w
                delay 0.2
                -- Close via menu: File > Close, or just Cmd+W
                keystroke "w" using command down
                delay 0.3
                exit repeat
            end if
        end repeat
    end tell
end tell
"""
        try:
            _run_applescript(script, timeout=10)
        except Exception:
            pass  # Best-effort — don't raise on cleanup
        self._console_open = False

    def close(self) -> None:
        """Close the Scripting Console window and clean up temp directory."""
        self._close_console_window()
        self._tmp_dir_obj.cleanup()
        self._console_open = False


# ---------------------------------------------------------------------------
# SAP element proxy
# ---------------------------------------------------------------------------

class _SAPElement:
    """Proxy for a SAP GUI element, accessed by ID via the JS bridge.

    Provides the same interface as Windows COM element objects:
    ``.text``, ``.press()``, ``.sendVKey()``, ``.select()``, etc.
    """

    def __init__(self, bridge: _ScriptingBridge, element_id: str) -> None:
        self._bridge = bridge
        self._id = element_id

    def _js_ref(self) -> str:
        return f'ses.findById("{self._id}")'

    @property
    def text(self) -> str:
        """Get the element's text value."""
        return self._bridge.execute(f'{self._js_ref()}.text') or ""

    @text.setter
    def text(self, value: str) -> None:
        """Set the element's text value."""
        escaped = (
            str(value)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", "\\n")
        )
        self._bridge.execute(
            f'{self._js_ref()}.text = "{escaped}"', void=True
        )

    def press(self) -> None:
        # Button presses can trigger blocking SAP operations (save,
        # execute, etc.), so allow a generous timeout.
        self._bridge.execute(
            f"{self._js_ref()}.press()", void=True, timeout=120.0
        )

    def sendVKey(self, vkey: int) -> None:
        # sendVKey blocks the SAP JS engine until the server responds.
        # F8 (Execute) can trigger multi-minute report queries, so we
        # allow up to 5 minutes.
        self._bridge.execute(
            f"{self._js_ref()}.sendVKey({vkey})",
            void=True,
            timeout=300.0,
        )

    def select(self) -> None:
        self._bridge.execute(f"{self._js_ref()}.select()", void=True)

    def close(self) -> None:
        self._bridge.execute(f"{self._js_ref()}.close()", void=True)

    def pressToolbarContextButton(self, button_id: str) -> None:
        escaped = button_id.replace("\\", "\\\\").replace('"', '\\"')
        self._bridge.execute(
            f'{self._js_ref()}.pressToolbarContextButton("{escaped}")', void=True
        )

    def selectContextMenuItem(self, item_id: str) -> None:
        escaped = item_id.replace("\\", "\\\\").replace('"', '\\"')
        self._bridge.execute(
            f'{self._js_ref()}.selectContextMenuItem("{escaped}")', void=True
        )

    def __getattr__(self, name: str):
        """Fallback: read a property, converting PascalCase → camelCase.

        Handles ``MessageType`` → ``messageType``, ``Text`` → ``text``, etc.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        camel = _pascal_to_camel(name)
        return self._bridge.execute(f"{self._js_ref()}.{camel}")


# ---------------------------------------------------------------------------
# Session.Info proxy
# ---------------------------------------------------------------------------

class _SAPInfo:
    """Proxy for ``session.Info`` — converts PascalCase attribute access
    to camelCase JS property reads.
    """

    def __init__(self, bridge: _ScriptingBridge) -> None:
        self._bridge = bridge

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        camel = _pascal_to_camel(name)
        return self._bridge.execute(f"ses.info.{camel}")


# ---------------------------------------------------------------------------
# Public API — same interface as Windows SAPSession
# ---------------------------------------------------------------------------

class SAPSession:
    """Connects to SAP GUI for Java on macOS via the Scripting Console.

    Provides the same interface as the Windows COM-based SAPSession:
    ``connect()``, ``disconnect()``, ``.session`` property, and
    context manager support.
    """

    def __init__(
        self,
        connection_index: int | None = None,
        session_index: int = 0,
        *,
        auto_launch: bool = False,
        connection_string: str | None = None,
    ):
        if connection_index is not None or session_index != 0:
            log.warning(
                "connection_index/session_index are ignored on macOS — "
                "the bridge always connects to the first active session"
            )
        self._auto_launch = auto_launch
        self._connection_string = connection_string
        self._bridge: _ScriptingBridge | None = None
        self._info: _SAPInfo | None = None

    # ------------------------------------------------------------------
    # Launch helpers
    # ------------------------------------------------------------------

    def _launch_sapgui(self, conn_str: str | None) -> None:
        """Launch SAP GUI for Java, optionally opening a connection.

        Blocks until the SAPGUI process appears (up to 30 s).

        Args:
            conn_str: SAP connection string (``/H/<host>/S/<port>``).
                If provided, ``-o`` and ``-b`` flags are passed so
                that the app connects immediately without a splash.
        """
        cmd = ["open", _SAPGUI_APP]
        if conn_str:
            cmd += ["--args", "-o", conn_str, "-b"]
            log.info("Launching SAP GUI with connection %s ...", conn_str)
        else:
            log.info("Launching SAP GUI (no connection string found)...")
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            time.sleep(1)
            if _is_sapgui_running():
                return
        raise SAPConnectionError(
            f"SAP GUI did not start within 30s. Ensure {_SAPGUI_APP} is installed."
        )

    @staticmethod
    def _kill_sapgui() -> None:
        """Terminate any running SAPGUI processes and wait for exit."""
        log.info("Stopping stale SAP GUI process...")
        subprocess.run(["pkill", "-x", "SAPGUI"], capture_output=True)
        for _ in range(15):
            time.sleep(1)
            if not _is_sapgui_running():
                return
        # Force-kill if graceful shutdown didn't work
        subprocess.run(["pkill", "-9", "-x", "SAPGUI"], capture_output=True)
        for _ in range(5):
            time.sleep(1)
            if not _is_sapgui_running():
                return
        raise SAPConnectionError("Could not stop existing SAP GUI process.")

    def _poll_for_session(self, *, timeout: float, interval: float) -> bool:
        """Poll the bridge until the SAP session object is accessible.

        Uses ``ses.id`` as the probe — this works on both the login screen
        and a logged-in session, unlike ``ses.info.systemName`` which only
        succeeds after authentication.

        Each probe uses a short bridge timeout so that the outer loop
        can decide when to give up and try a different strategy (e.g.
        kill + relaunch).

        Returns True on success, False on timeout.
        """
        # Per-probe bridge timeout — short enough for several retries
        # within the outer timeout, long enough for one round-trip when
        # the session IS responsive.
        probe_timeout = min(10.0, timeout)
        deadline = time.monotonic() + timeout
        while True:
            try:
                ses_id = self._bridge.execute(
                    "ses.id", timeout=probe_timeout
                )
                log.info("SAP session ready (id=%s)", ses_id)
                return True
            except SAPConnectionError:
                if time.monotonic() >= deadline:
                    return False
                log.debug(
                    "Session not ready yet, retrying in %.0fs...", interval
                )
                self._bridge.reset()
                time.sleep(interval)

    # ------------------------------------------------------------------
    # Public connect / disconnect
    # ------------------------------------------------------------------

    def connect(self, *, auto_launch: bool | None = None) -> None:
        """Verify SAP GUI is running and open the Scripting Console bridge.

        When *auto_launch* is True the method guarantees a working
        session by the time it returns:

        1. If SAP GUI is **not running** → launch with ``-o <conn_str> -b``
           and poll until the login screen is reachable.
        2. If SAP GUI **is running but has no session** (stale process,
           window closed, etc.) → kill it, relaunch, and poll.
        3. If SAP GUI **is running with an active session** → connect
           immediately.

        Args:
            auto_launch: If True and no session is reachable, launch /
                restart SAP GUI automatically.  If None, falls back to
                the value passed to ``__init__``.
        """
        if auto_launch is None:
            auto_launch = self._auto_launch

        conn_str = (
            (self._connection_string or _detect_connection_string())
            if auto_launch
            else None
        )

        launched = False
        if not _is_sapgui_running():
            if not auto_launch:
                raise SAPConnectionError(
                    "SAP GUI is not running. Please open SAP GUI for Java "
                    "and connect to a system first."
                )
            self._launch_sapgui(conn_str)
            launched = True

        self._bridge = _ScriptingBridge()

        if launched:
            time.sleep(5)  # let the app initialise before first probe

        # Open the Scripting Console before polling — required for the JS
        # bridge to work on both login screen and logged-in sessions.
        try:
            self._bridge._open_console()
        except SAPConnectionError:
            pass  # Will be caught by the poll below

        # First poll — moderate timeout if we didn't launch (enough for
        # 1-2 bridge probes), longer if we just started it.
        timeout = 90.0 if launched else 30.0
        interval = 3.0 if launched else 2.0

        if self._poll_for_session(timeout=timeout, interval=interval):
            self._info = _SAPInfo(self._bridge)
            return

        # Session unreachable — try opening the Scripting Console explicitly
        # via the Scripts menu before giving up.  This handles the common case
        # where SAP is running and logged in but the console was never opened.
        log.info("Session not reachable, attempting to open Scripting Console...")
        try:
            self._bridge._open_console()
            self._bridge.reset()
        except SAPConnectionError:
            pass

        if self._poll_for_session(timeout=60.0, interval=3.0):
            self._info = _SAPInfo(self._bridge)
            return

        # Without auto_launch we give up.
        if not auto_launch:
            self._bridge.close()
            self._bridge = None
            raise SAPConnectionError(
                "Could not communicate with SAP session via "
                "Scripting Console. Ensure you are logged into "
                "a SAP system."
            )

        # auto_launch: SAP GUI is running but the session is still not reachable
        # after opening the Scripting Console. This likely means we are at a
        # login screen (after a restart or session expiry). Only kill + relaunch
        # if SAP is NOT showing a logged-in session — i.e. if the scripting
        # bridge really cannot reach ses.info.systemName at all.
        # Check if there's any open SAP session window before killing.
        try:
            win_count_result = _run_applescript("""\
tell application "System Events"
    tell process "SAPGUI"
        return count of windows
    end tell
end tell
""", timeout=5)
            win_count = int(win_count_result.strip()) if win_count_result.strip().isdigit() else 0
        except Exception:
            win_count = 0

        if win_count > 1:
            # Multiple windows suggest an active logged-in session.
            # Try once more to open the Scripting Console — there may be
            # a blocking dialog that clears on its own, or the console
            # was simply never opened after a fresh login.
            log.info("SAP has %d windows; retrying Scripting Console open...", win_count)
            try:
                self._bridge._open_console()
                self._bridge.reset()
            except SAPConnectionError:
                pass

            if self._poll_for_session(timeout=30.0, interval=3.0):
                self._info = _SAPInfo(self._bridge)
                return

            # Still unreachable — give up without killing the live session.
            self._bridge.close()
            self._bridge = None
            raise SAPConnectionError(
                "SAP GUI is running with an active session but the "
                "Scripting Console bridge could not be established. "
                "Please ensure the Scripting Console is open and "
                "the SAP session is responsive."
            )

        # Only one window (connection picker) — safe to kill and relaunch.
        # auto_launch: SAP GUI is running but has no usable session
        # (e.g. stale process, window closed).  Kill and restart.
        self._bridge.close()
        self._kill_sapgui()
        self._launch_sapgui(conn_str)
        self._bridge = _ScriptingBridge()
        time.sleep(5)

        if self._poll_for_session(timeout=90.0, interval=3.0):
            self._info = _SAPInfo(self._bridge)
            return

        self._bridge.close()
        self._bridge = None
        raise SAPConnectionError(
            "Could not communicate with SAP session after restarting "
            "SAP GUI. Check your connection string and network."
        )

    def disconnect(self) -> None:
        """Close the bridge (does NOT close SAP GUI)."""
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None
        self._info = None

    @property
    def session(self):
        """Return self — this object implements findById() and .Info directly."""
        if self._bridge is None:
            raise SAPConnectionError(
                "Not connected. Call connect() first or use as context manager."
            )
        return self

    def findById(self, element_id: str) -> _SAPElement:
        """Return a proxy for the SAP element with the given ID."""
        if self._bridge is None:
            raise SAPConnectionError("Not connected.")
        return _SAPElement(self._bridge, element_id)

    def startTransaction(self, tcode: str) -> None:
        """Start a transaction, closing any modal popups.

        This is more robust than setting okcd + Enter, because it
        bypasses modal windows that block normal keyboard navigation
        (e.g. the spreadsheet viewer popup after a list export).
        """
        if self._bridge is None:
            raise SAPConnectionError("Not connected.")
        escaped = tcode.replace("\\", "\\\\").replace('"', '\\"')
        self._bridge.execute(
            f'ses.startTransaction("{escaped}")', void=True, timeout=30.0
        )

    def execute_js(
        self,
        js_expression: str,
        *,
        void: bool = False,
        timeout: float = 30.0,
    ) -> str | None:
        """Execute raw JavaScript via the Scripting Console bridge.

        The expression can reference ``ses`` (the current SAP session).
        Use this for operations that require chained property access or
        other constructs that the element proxy cannot express.
        """
        if self._bridge is None:
            raise SAPConnectionError("Not connected.")
        return self._bridge.execute(js_expression, void=void, timeout=timeout)

    @property
    def Info(self) -> _SAPInfo:
        """Return the session Info proxy (PascalCase for Windows API compat)."""
        if self._info is None:
            raise SAPConnectionError("Not connected.")
        return self._info

    def __enter__(self) -> SAPSession:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


class SAPSessionManager:
    """Stub for macOS — multi-session management is not yet supported.

    Matches the Windows ``SAPSessionManager`` constructor signature so that
    imports work without errors. Actual methods raise ``NotImplementedError``.
    """

    def __init__(
        self,
        username: str,
        password: str,
        language: str = "ZH",
    ):
        self._username = username
        self._password = password
        self._language = language

    def connect(self) -> None:
        raise NotImplementedError("SAPSessionManager not yet supported on macOS")

    def create_session(self) -> object:
        raise NotImplementedError("SAPSessionManager not yet supported on macOS")

    def disconnect(self) -> None:
        pass

    @property
    def primary_session(self):
        raise NotImplementedError("SAPSessionManager not yet supported on macOS")

    def run_parallel(
        self,
        tasks: list,
        max_sessions: int = 5,
    ) -> list:
        raise NotImplementedError("SAPSessionManager not yet supported on macOS")

    def __enter__(self) -> SAPSessionManager:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
