"""db_client — PostgreSQL client for Haidilao automation."""

from .client import Database
from .errors import DBConnectionError, DBError, DBQueryError
from .pool import get_db

__all__ = [
    "Database",
    "get_db",
    "DBError",
    "DBConnectionError",
    "DBQueryError",
]
