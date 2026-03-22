"""Server-level DB layer — thin wrappers around db-client for store targets / competitors.

DATABASE_URL is optional. All functions degrade gracefully when no DB is configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db_client import Database

logger = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────

_db: "Database | None" = None
_db_attempted = False  # True once we've tried (and possibly failed) to connect


def get_db() -> "Database | None":
    """Return the singleton Database, or None if DATABASE_URL is not set."""
    global _db, _db_attempted
    if _db_attempted:
        return _db
    _db_attempted = True

    from server.config import settings
    url = settings.database_url
    if not url:
        logger.debug("DATABASE_URL not set — DB layer disabled")
        return None

    try:
        from db_client import Database
        _db = Database(dsn=url)
        logger.info("DB connection pool opened")
    except Exception as exc:
        logger.warning("Could not connect to DB: %s — falling back to JSON", exc)
        _db = None
    return _db


def is_db_available() -> bool:
    """Return True when a DB connection is available."""
    return get_db() is not None


# ── Target CRUD ───────────────────────────────────────────────────────────────

_SLOTS = ["08:00-13:59", "14:00-16:59", "17:00-21:59", "22:00-(次)07:59"]


def get_targets(month_key: str) -> dict:
    """Return targets for *month_key* in the same shape as targets.json.

    Shape::

        {
            "revenue": {"加拿大一店": 116.07, ...},
            "turnover_rate": {
                "加拿大一店": {
                    "08:00-13:59": 1.00,
                    ...
                    "total": 4.60
                },
                ...
            }
        }
    """
    db = get_db()
    if db is None:
        return {"revenue": {}, "turnover_rate": {}}

    rows = db.fetchall(
        "SELECT store_name, revenue, tr_slot_1, tr_slot_2, tr_slot_3, tr_slot_4, tr_total "
        "FROM store_targets WHERE month_key = %s",
        (month_key,),
    )

    revenue: dict[str, float] = {}
    turnover_rate: dict[str, dict[str, float]] = {}
    for row in rows:
        store = row["store_name"]
        revenue[store] = float(row["revenue"])
        turnover_rate[store] = {
            _SLOTS[0]: float(row["tr_slot_1"]),
            _SLOTS[1]: float(row["tr_slot_2"]),
            _SLOTS[2]: float(row["tr_slot_3"]),
            _SLOTS[3]: float(row["tr_slot_4"]),
            "total": float(row["tr_total"]),
        }

    return {"revenue": revenue, "turnover_rate": turnover_rate}


def set_targets(
    month_key: str,
    store: str,
    revenue: float,
    tr_slot_1: float,
    tr_slot_2: float,
    tr_slot_3: float,
    tr_slot_4: float,
    tr_total: float,
) -> None:
    """Upsert a single store's targets for *month_key*."""
    db = get_db()
    if db is None:
        raise RuntimeError("DB not available")

    db.execute(
        """
        INSERT INTO store_targets
            (month_key, store_name, revenue, tr_slot_1, tr_slot_2, tr_slot_3, tr_slot_4, tr_total, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (month_key, store_name)
        DO UPDATE SET
            revenue   = EXCLUDED.revenue,
            tr_slot_1 = EXCLUDED.tr_slot_1,
            tr_slot_2 = EXCLUDED.tr_slot_2,
            tr_slot_3 = EXCLUDED.tr_slot_3,
            tr_slot_4 = EXCLUDED.tr_slot_4,
            tr_total  = EXCLUDED.tr_total,
            updated_at = NOW()
        """,
        (month_key, store, revenue, tr_slot_1, tr_slot_2, tr_slot_3, tr_slot_4, tr_total),
    )


def has_targets(month_key: str) -> bool:
    """Return True if at least one store target row exists for *month_key*."""
    db = get_db()
    if db is None:
        return False
    row = db.fetchone(
        "SELECT 1 FROM store_targets WHERE month_key = %s LIMIT 1",
        (month_key,),
    )
    return row is not None


def get_all_months() -> list[str]:
    """Return all distinct month_key values, sorted descending."""
    db = get_db()
    if db is None:
        return []
    rows = db.fetchall(
        "SELECT DISTINCT month_key FROM store_targets ORDER BY month_key DESC"
    )
    return [r["month_key"] for r in rows]


# ── Competitor CRUD ───────────────────────────────────────────────────────────


def get_competitors() -> dict[str, str]:
    """Return {store: competitor_store} for all rows."""
    db = get_db()
    if db is None:
        return {}
    rows = db.fetchall("SELECT store_name, competitor_name FROM store_competitors")
    return {r["store_name"]: r["competitor_name"] for r in rows}


def set_competitor(store: str, competitor: str) -> None:
    """Upsert a single store → competitor mapping."""
    db = get_db()
    if db is None:
        raise RuntimeError("DB not available")

    db.execute(
        """
        INSERT INTO store_competitors (store_name, competitor_name, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (store_name)
        DO UPDATE SET competitor_name = EXCLUDED.competitor_name, updated_at = NOW()
        """,
        (store, competitor),
    )


def has_competitors() -> bool:
    """Return True if at least one competitor row exists."""
    db = get_db()
    if db is None:
        return False
    row = db.fetchone("SELECT 1 FROM store_competitors LIMIT 1")
    return row is not None


# ── JSON migration ────────────────────────────────────────────────────────────


def migrate_from_json(targets_json_path: Path, competitor_json_path: Path) -> None:
    """One-time import of JSON files into DB. Skips entries that already exist."""
    import json

    db = get_db()
    if db is None:
        logger.warning("migrate_from_json: DB not available, skipping")
        return

    # Targets
    try:
        with open(targets_json_path, encoding="utf-8") as f:
            targets_data: dict = json.load(f)

        for month_key, month_data in targets_data.items():
            revenue_map = month_data.get("revenue", {})
            tr_map = month_data.get("turnover_rate", {})
            for store, revenue in revenue_map.items():
                # Check if already exists
                existing = db.fetchone(
                    "SELECT 1 FROM store_targets WHERE month_key=%s AND store_name=%s",
                    (month_key, store),
                )
                if existing:
                    continue
                tr = tr_map.get(store, {})
                db.execute(
                    """
                    INSERT INTO store_targets
                        (month_key, store_name, revenue, tr_slot_1, tr_slot_2, tr_slot_3, tr_slot_4, tr_total)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        month_key,
                        store,
                        float(revenue),
                        float(tr.get(_SLOTS[0], 0)),
                        float(tr.get(_SLOTS[1], 0)),
                        float(tr.get(_SLOTS[2], 0)),
                        float(tr.get(_SLOTS[3], 0)),
                        float(tr.get("total", 0)),
                    ),
                )
        logger.info("migrate_from_json: targets imported from %s", targets_json_path)
    except FileNotFoundError:
        logger.warning("migrate_from_json: targets file not found: %s", targets_json_path)
    except Exception as exc:
        logger.error("migrate_from_json: targets import failed: %s", exc)

    # Competitors
    try:
        with open(competitor_json_path, encoding="utf-8") as f:
            comp_data: dict = json.load(f)

        for store, competitor in comp_data.items():
            existing = db.fetchone(
                "SELECT 1 FROM store_competitors WHERE store_name=%s",
                (store,),
            )
            if existing:
                continue
            db.execute(
                "INSERT INTO store_competitors (store_name, competitor_name) VALUES (%s, %s)",
                (store, competitor),
            )
        logger.info("migrate_from_json: competitors imported from %s", competitor_json_path)
    except FileNotFoundError:
        logger.warning("migrate_from_json: competitor file not found: %s", competitor_json_path)
    except Exception as exc:
        logger.error("migrate_from_json: competitor import failed: %s", exc)


# ── Startup migrations ────────────────────────────────────────────────────────


def maybe_run_migrations() -> None:
    """Run DB schema migrations if DATABASE_URL is set. No-op otherwise."""
    db = get_db()
    if db is None:
        return

    # migrations_dir = <repo_root>/docker/init/
    # server/src/server/db.py → up 4 levels = repo root
    migrations_dir = Path(__file__).resolve().parent.parent.parent.parent / "docker" / "init"

    try:
        from db_client.migrations import run_migrations
        run_migrations(db, migrations_dir)
    except Exception as exc:
        logger.error("maybe_run_migrations: failed: %s", exc)


# ── Report helpers ────────────────────────────────────────────────────────────


def get_targets_for_report(month_key: str) -> dict:
    """Return targets for the report from DB.

    Returns empty dicts if DB is not available or month has no targets.
    Callers should use has_targets() first if they need to distinguish
    between 'DB unavailable' and 'no data'.
    """
    if not is_db_available():
        logger.warning("get_targets_for_report: DB not available, returning empty targets")
        return {"revenue": {}, "turnover_rate": {}}
    return get_targets(month_key)


def get_competitor_for_report() -> dict[str, str]:
    """Return competitor map from DB.

    Returns empty dict if DB is not available or no competitors configured.
    """
    if not is_db_available():
        logger.warning("get_competitor_for_report: DB not available, returning empty map")
        return {}
    return get_competitors()


# ── Admin users ───────────────────────────────────────────────────────────────


def upsert_admin_user(open_id: str, name: str, avatar_url: str = "") -> None:
    """Record a login attempt. Creates the user if new, updates last_seen if existing."""
    db = get_db()
    if db is None:
        return
    db.execute(
        """
        INSERT INTO admin_users (open_id, name, avatar_url, first_seen_at, last_seen_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON CONFLICT (open_id) DO UPDATE SET
            name         = EXCLUDED.name,
            avatar_url   = EXCLUDED.avatar_url,
            last_seen_at = NOW()
        """,
        (open_id, name, avatar_url),
    )


def is_db_whitelisted(open_id: str) -> bool:
    """Return True if the user is whitelisted in the DB."""
    db = get_db()
    if db is None:
        return False
    row = db.fetchone(
        "SELECT whitelisted FROM admin_users WHERE open_id = %s",
        (open_id,),
    )
    return bool(row and row["whitelisted"])


def set_admin_whitelist(open_id: str, whitelisted: bool) -> None:
    """Grant or revoke whitelist status for a user."""
    db = get_db()
    if db is None:
        raise RuntimeError("DB not available")
    db.execute(
        "UPDATE admin_users SET whitelisted = %s WHERE open_id = %s",
        (whitelisted, open_id),
    )


def get_admin_users() -> list[dict]:
    """Return all admin_users rows, ordered by last_seen desc."""
    db = get_db()
    if db is None:
        return []
    return db.fetchall(
        "SELECT open_id, name, avatar_url, whitelisted, first_seen_at, last_seen_at "
        "FROM admin_users ORDER BY last_seen_at DESC"
    )
