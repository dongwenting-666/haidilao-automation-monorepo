"""Custom exception hierarchy for SAP GUI automation."""


class SAPGuiError(Exception):
    """Base exception for SAP GUI automation errors."""


class SAPConnectionError(SAPGuiError):
    """SAP GUI is not running or no session is available."""


class SAPNavigationError(SAPGuiError):
    """Transaction navigation or field interaction failed."""


class SAPExportError(SAPGuiError):
    """File export operation failed."""


class SAPStatusBarError(SAPGuiError):
    """SAP status bar reported an error or abort message."""

    def __init__(self, message: str, message_type: str):
        self.message_text = message
        self.message_type = message_type
        super().__init__(f"SAP status bar [{message_type}]: {message}")
