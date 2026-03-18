"""DB error hierarchy."""

from __future__ import annotations


class DBError(Exception):
    """Base error for all db-client exceptions."""


class DBConnectionError(DBError):
    """Raised when the connection pool cannot be established or a connection fails."""


class DBQueryError(DBError):
    """Raised when a query execution fails."""
