"""Module-level singleton Database — lazy-initialised from DATABASE_URL."""

from __future__ import annotations

from .client import Database

_db: Database | None = None


def get_db() -> Database:
    """Return the module-level :class:`~db_client.Database` singleton.

    On first call the pool is opened using the ``DATABASE_URL`` environment
    variable.  Subsequent calls return the same instance.

    Returns:
        The shared :class:`~db_client.Database` instance.

    Raises:
        :class:`~db_client.errors.DBConnectionError`: if ``DATABASE_URL`` is
        not set or the pool cannot be opened.
    """
    global _db
    if _db is None:
        _db = Database()
    return _db
