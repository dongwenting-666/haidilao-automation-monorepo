"""Lark client error hierarchy."""


class LarkError(Exception):
    """Base error for Lark client operations."""


class LarkAuthError(LarkError):
    """Failed to obtain or refresh the tenant access token."""


class LarkAPIError(LarkError):
    """Lark API returned a non-zero code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"Lark API error {code}: {message}")
        self.code = code
        self.message = message
