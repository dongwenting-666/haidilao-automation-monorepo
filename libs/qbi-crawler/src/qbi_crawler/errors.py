"""Exception hierarchy for QBI crawler."""


class QBIError(Exception):
    """Base exception for QBI operations."""


class QBILoginError(QBIError):
    """Failed to authenticate with Quick BI."""


class QBITimeoutError(QBIError):
    """Operation timed out waiting for page/element."""
