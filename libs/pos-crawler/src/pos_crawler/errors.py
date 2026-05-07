"""Exception hierarchy for POS crawler."""


class POSError(Exception):
    """Base exception for POS operations."""


class POSLoginExpiredError(POSError):
    """Saved session has expired — manual re-authentication required."""


class POSTimeoutError(POSError):
    """Operation timed out waiting for page/element."""
