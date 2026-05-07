"""Exception hierarchy for SAP Fiori crawler."""


class FioriError(Exception):
    """Base exception for SAP Fiori operations."""


class FioriLoginError(FioriError):
    """Login failed after exhausting retries."""


class FioriTimeoutError(FioriError):
    """Operation timed out waiting for page/element."""


class FioriExportError(FioriError):
    """Stocktake export failed (no download produced or response was malformed)."""
