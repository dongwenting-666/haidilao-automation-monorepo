"""Transaction navigation and field/button helpers for SAP GUI."""

from __future__ import annotations

from sap_gui.errors import SAPNavigationError, SAPStatusBarError


class SAPNavigator:
    """Provides helpers for navigating transactions and interacting with fields."""

    def __init__(self, session) -> None:
        self._session = session

    def login(self, username: str, password: str, language: str = "ZH") -> None:
        """Log in to SAP from the login screen. Skips if already logged in."""
        import time

        try:
            if self._session.Info.User:
                return  # Already authenticated
        except Exception:
            pass  # On login screen, Info.User is not yet available

        # Wait for login screen fields to become ready
        for _ in range(20):
            try:
                self._session.findById("wnd[0]/usr/txtRSYST-BNAME").text = username
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SAPNavigationError("Login screen did not become ready")

        self.set_field("wnd[0]/usr/pwdRSYST-BCODE", password)
        self.set_field("wnd[0]/usr/txtRSYST-LANGU", language)
        self.send_vkey(0)  # Enter
        self.check_status_bar()

    def run_transaction(self, tcode: str) -> None:
        """Navigate to a transaction by code (e.g. 'KSB1')."""
        try:
            self._session.findById("wnd[0]/tbar[0]/okcd").text = f"/n{tcode}"
        except Exception as exc:
            raise SAPNavigationError(
                f"Failed to navigate to transaction {tcode}"
            ) from exc
        self.send_vkey(0)  # Enter
        self.check_status_bar()

    def set_field(self, field_id: str, value: str) -> None:
        """Set a text field value by its SAP element ID."""
        try:
            self._session.findById(field_id).text = value
        except Exception as exc:
            raise SAPNavigationError(
                f"Failed to set field {field_id}"
            ) from exc

    def press_button(self, button_id: str) -> None:
        """Press a button by its SAP element ID."""
        try:
            self._session.findById(button_id).press()
        except Exception as exc:
            raise SAPNavigationError(
                f"Failed to press button {button_id}"
            ) from exc

    def send_vkey(self, vkey: int, window: int = 0) -> None:
        """Send a virtual key to a SAP window.

        Common vkeys: 0=Enter, 3=Back, 8=F8/Execute, 11=Save, 12=Cancel.
        """
        try:
            self._session.findById(f"wnd[{window}]").sendVKey(vkey)
        except Exception as exc:
            raise SAPNavigationError(
                f"Failed to send vkey {vkey} to window {window}"
            ) from exc

    def check_status_bar(self) -> None:
        """Read the status bar and raise on error/abort messages."""
        try:
            status_bar = self._session.findById("wnd[0]/sbar")
        except Exception:
            return  # Status bar not available, skip check

        msg_type = status_bar.MessageType
        if msg_type in ("E", "A"):
            raise SAPStatusBarError(status_bar.Text, msg_type)

    def select_menu(self, menu_id: str) -> None:
        """Select a menu item by its SAP element ID.

        Example: "wnd[0]/mbar/menu[0]/menu[3]/menu[1]" for List -> Export -> Spreadsheet.
        """
        try:
            self._session.findById(menu_id).select()
        except Exception as exc:
            raise SAPNavigationError(
                f"Failed to select menu {menu_id}"
            ) from exc

    def close_window(self, window: int = 1) -> bool:
        """Close a SAP window. Returns True if closed successfully."""
        try:
            self._session.findById(f"wnd[{window}]").close()
            return True
        except Exception:
            return False

    def dismiss_popup(self, window: int = 1, vkey: int = 0) -> bool:
        """Try to dismiss a modal popup window. Returns True if dismissed."""
        try:
            self._session.findById(f"wnd[{window}]").sendVKey(vkey)
            return True
        except Exception:
            return False
