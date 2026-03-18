"""Database client — sync wrapper around psycopg3 ConnectionPool."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .errors import DBConnectionError, DBQueryError

_Params = tuple[Any, ...] | list[Any] | dict[str, Any] | None


class Database:
    """Thin sync wrapper around a psycopg3 ConnectionPool.

    Usage::

        db = Database()          # reads DATABASE_URL from env
        db = Database(dsn="postgresql://...")

        # as a context manager
        with Database() as db:
            rows = db.fetchall("SELECT * FROM store_targets")

        # explicit lifecycle
        db = Database()
        db.execute("INSERT INTO ...")
        db.close()
    """

    def __init__(self, dsn: str | None = None) -> None:
        resolved = dsn or os.environ.get("DATABASE_URL")
        if not resolved:
            raise DBConnectionError(
                "No DSN provided and DATABASE_URL env var is not set."
            )
        try:
            self._pool = ConnectionPool(
                conninfo=resolved,
                kwargs={"row_factory": dict_row},
                open=True,
            )
        except Exception as exc:
            raise DBConnectionError(f"Failed to open connection pool: {exc}") from exc

    # ------------------------------------------------------------------
    # Core query helpers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: _Params = None) -> None:
        """Execute a statement, discarding any result."""
        try:
            with self._pool.connection() as conn:
                conn.execute(sql, params)
        except psycopg.Error as exc:
            raise DBQueryError(f"Query failed: {exc}") from exc

    def fetchone(self, sql: str, params: _Params = None) -> dict[str, Any] | None:
        """Return the first row as a dict, or None if no rows."""
        try:
            with self._pool.connection() as conn:
                cur = conn.execute(sql, params)
                return cur.fetchone()
        except psycopg.Error as exc:
            raise DBQueryError(f"Query failed: {exc}") from exc

    def fetchall(self, sql: str, params: _Params = None) -> list[dict[str, Any]]:
        """Return all rows as a list of dicts."""
        try:
            with self._pool.connection() as conn:
                cur = conn.execute(sql, params)
                return cur.fetchall()
        except psycopg.Error as exc:
            raise DBQueryError(f"Query failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Transaction context manager
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Generator[psycopg.Connection, None, None]:
        """Context manager that yields a connection inside a transaction.

        Commits on clean exit, rolls back on exception::

            with db.transaction() as conn:
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
        """
        try:
            with self._pool.connection() as conn:
                with conn.transaction():
                    yield conn
        except psycopg.Error as exc:
            raise DBQueryError(f"Transaction failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._pool.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
