"""COM connection to a running SAP GUI instance."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from sap_gui.errors import SAPConnectionError

log = logging.getLogger(__name__)


def _get_application():
    """Get the SAP GUI scripting engine via COM."""
    import win32com.client

    try:
        sap_gui = win32com.client.GetObject("SAPGUI")
    except Exception as exc:
        raise SAPConnectionError(
            "SAP GUI is not running. Please open SAP Logon first."
        ) from exc

    try:
        return sap_gui.GetScriptingEngine
    except Exception as exc:
        raise SAPConnectionError(
            "Could not get SAP scripting engine. "
            "Ensure scripting is enabled in SAP GUI options."
        ) from exc


def _find_live_connection(application):
    """Find the first responsive connection, skipping stale ones."""
    count = application.Children.Count
    if count == 0:
        raise SAPConnectionError("No SAP connections found. Please open a system.")

    for i in range(count):
        conn = application.Children(i)
        if conn.Children.Count == 0:
            continue
        session = conn.Children(0)
        try:
            session.findById("wnd[0]")
            return conn, i
        except Exception:
            continue

    raise SAPConnectionError(
        "No responsive SAP connections found. All sessions may be stale — "
        "please close SAP GUI completely and re-open."
    )


def _wait_for_session(session, timeout: float = 10.0) -> None:
    """Wait until a session's main window is accessible."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            session.findById("wnd[0]")
            return
        except Exception:
            time.sleep(0.5)
    raise SAPConnectionError("Session did not become ready in time.")


class SAPSession:
    """Connects to an already-running SAP GUI process via COM/ActiveX.

    Automatically finds the first live connection, skipping stale ones.
    """

    def __init__(self, connection_index: int | None = None, session_index: int = 0):
        self._connection_index = connection_index
        self._session_index = session_index
        self._session = None
        self._application = None

    def connect(self) -> None:
        """Attach to an existing SAP GUI session via COM."""
        self._application = _get_application()

        if self._connection_index is not None:
            try:
                connection = self._application.Children(self._connection_index)
            except Exception as exc:
                raise SAPConnectionError(
                    f"Connection index {self._connection_index} not available."
                ) from exc
        else:
            connection, _ = _find_live_connection(self._application)

        if connection.Children.Count == 0:
            raise SAPConnectionError(
                "No sessions found on this connection."
            )

        try:
            self._session = connection.Children(self._session_index)
        except Exception as exc:
            raise SAPConnectionError(
                f"Session index {self._session_index} not available."
            ) from exc

        _wait_for_session(self._session)

    def disconnect(self) -> None:
        """Release COM references (does NOT close SAP GUI)."""
        self._session = None
        self._application = None

    @property
    def session(self):
        """Return the raw GuiSession COM object."""
        if self._session is None:
            raise SAPConnectionError(
                "Not connected. Call connect() first or use as context manager."
            )
        return self._session

    def __enter__(self) -> SAPSession:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


class SAPSessionManager:
    """Manages multiple SAP GUI sessions for parallel automation.

    Logs in once, then creates additional sessions via /o command.
    SAP typically allows up to 6 sessions per connection.

    Usage:
        with SAPSessionManager("user", "pass") as mgr:
            results = mgr.run_parallel([
                lambda ses: process_a(ses),
                lambda ses: process_b(ses),
            ])
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
        self._application = None
        self._connection = None
        self._primary_session = None

    def connect(self) -> None:
        """Connect and log in, creating the primary session."""
        from sap_gui.navigation import SAPNavigator

        self._application = _get_application()
        self._connection, _ = _find_live_connection(self._application)
        self._primary_session = self._connection.Children(0)
        _wait_for_session(self._primary_session)

        nav = SAPNavigator(self._primary_session)
        nav.login(self._username, self._password, self._language)
        log.info("Logged in as %s", self._primary_session.Info.User)

    def create_session(self) -> object:
        """Create an additional SAP session from the primary one.

        Returns the new raw GuiSession COM object.
        """
        current_count = self._connection.Children.Count
        self._primary_session.CreateSession()

        # Wait for the new session to appear
        for _ in range(20):
            if self._connection.Children.Count > current_count:
                new_session = self._connection.Children(current_count)
                _wait_for_session(new_session)
                return new_session
            time.sleep(0.5)

        raise SAPConnectionError("Failed to create new session — limit may be reached.")

    def disconnect(self) -> None:
        """Release COM references (does NOT close SAP GUI sessions)."""
        self._primary_session = None
        self._connection = None
        self._application = None

    @property
    def primary_session(self):
        """The first (logged-in) session."""
        return self._primary_session

    def run_parallel(
        self,
        tasks: list[Callable],
        max_sessions: int = 5,
    ) -> list:
        """Run tasks in parallel, each on its own SAP session.

        Args:
            tasks: List of callables. Each receives (session, navigator, exporter)
                   as a tuple.
            max_sessions: Max additional sessions to create (SAP limit is usually 5
                          extra = 6 total).

        Returns:
            List of results in the same order as tasks.
        """
        from sap_gui.export import SAPExporter
        from sap_gui.navigation import SAPNavigator

        if not tasks:
            return []

        num_extra = min(len(tasks) - 1, max_sessions)

        # First task uses the primary session
        sessions = [self._primary_session]
        for i in range(num_extra):
            log.info("Creating session %d/%d...", i + 1, num_extra)
            sessions.append(self.create_session())

        results = [None] * len(tasks)

        def _run_task(index: int, raw_session):
            import pythoncom
            pythoncom.CoInitialize()
            try:
                nav = SAPNavigator(raw_session)
                exporter = SAPExporter(raw_session, nav)
                return tasks[index](raw_session, nav, exporter)
            finally:
                pythoncom.CoUninitialize()

        with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
            futures = {}
            for i, task in enumerate(tasks):
                session = sessions[i % len(sessions)]
                future = pool.submit(_run_task, i, session)
                futures[future] = i

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    log.error("Task %d failed: %s", idx, exc)
                    raise

        return results

    def __enter__(self) -> SAPSessionManager:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
