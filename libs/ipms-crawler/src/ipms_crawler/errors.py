"""Exception hierarchy for IPMS crawler."""


class IPMSError(Exception):
    """Base exception for IPMS operations."""


class IPMSLoginExpiredError(IPMSError):
    """Saved session has expired — manual re-authentication required."""


class IPMSTimeoutError(IPMSError):
    """Operation timed out waiting for page/element."""


class IPMSExportError(IPMSError):
    """Export job failed or download could not be retrieved."""
