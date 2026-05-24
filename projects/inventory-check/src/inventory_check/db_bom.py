"""Reader for the ``store_bom`` table — per-store dish ↔ material recipe.

This is the inventory-check side of the system of record migrated in 2026-05:
the hand-curated 计算 sheet is now mirrored into Postgres (``store_bom``)
and edited via the /admin/bom UI. ``derive_calc_rows`` consumes the rows
returned here.
"""
from __future__ import annotations

import logging
from typing import Any

from db_client import get_db

logger = logging.getLogger(__name__)

_BOM_COLS = (
    "dish_code", "dish_name", "dish_short_code", "spec",
    "material_code", "material_name", "portion", "loss_factor", "unit",
    "packaging_factor",
)


def load_store_bom_rows(werks: str) -> list[dict[str, Any]]:
    """Return all recipe rows for ``werks`` from store_bom.

    Rows are returned as plain dicts with the column names of the
    ``store_bom`` table (one row per dish×spec×material). Order is stable
    by (dish_code, spec, material_code) so downstream output is
    deterministic.

    Raises RuntimeError when the DB is unavailable — callers that want a
    soft fallback should catch it.
    """
    db = get_db()
    if db is None:
        raise RuntimeError(
            "DATABASE_URL not set — cannot load BOM for werks=%s" % werks
        )
    sql = (
        f"SELECT {','.join(_BOM_COLS)} FROM store_bom "
        "WHERE werks = %s "
        "ORDER BY dish_code, spec, material_code"
    )
    rows = db.fetchall(sql, (werks,))
    logger.info("loaded %d BOM rows from store_bom for werks=%s",
                len(rows), werks)
    return rows
