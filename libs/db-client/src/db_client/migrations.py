"""Simple SQL migration runner.

Migrations are plain `.sql` files inside `migrations_dir`, run in
alphabetical order.  Applied filenames are tracked in a `_migrations`
table so re-runs are idempotent.
"""

from __future__ import annotations

from pathlib import Path

from .client import Database
from .errors import DBQueryError

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS _migrations (
    id          SERIAL PRIMARY KEY,
    filename    VARCHAR(255) NOT NULL UNIQUE,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""


def run_migrations(db: Database, migrations_dir: Path) -> None:
    """Apply all unapplied `.sql` files from *migrations_dir*.

    Args:
        db: An open :class:`~db_client.Database` instance.
        migrations_dir: Directory containing ``*.sql`` migration files.

    Raises:
        :class:`~db_client.errors.DBQueryError`: on any SQL error.
        FileNotFoundError: if *migrations_dir* does not exist.
    """
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"migrations_dir not found: {migrations_dir}")

    # Ensure the tracking table exists.
    db.execute(_CREATE_MIGRATIONS_TABLE)

    # Collect already-applied filenames.
    rows = db.fetchall("SELECT filename FROM _migrations ORDER BY filename")
    applied: set[str] = {row["filename"] for row in rows}

    # Run pending migrations in alphabetical order.
    sql_files = sorted(migrations_dir.glob("*.sql"))
    for sql_file in sql_files:
        filename = sql_file.name
        if filename in applied:
            continue

        sql = sql_file.read_text(encoding="utf-8")
        try:
            with db.transaction() as conn:
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO _migrations (filename) VALUES (%s)",
                    (filename,),
                )
        except DBQueryError as exc:
            raise DBQueryError(
                f"Migration '{filename}' failed: {exc}"
            ) from exc

        print(f"[migrations] applied: {filename}")

    if not sql_files:
        print("[migrations] no .sql files found — nothing to do")
