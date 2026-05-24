"""Tests for inventory_check.db_bom — store_bom reader."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inventory_check.db_bom import load_store_bom_rows


def test_load_store_bom_rows_passes_werks_and_orders():
    fake_rows = [
        {"dish_code": 1, "spec": "单锅", "material_code": 100},
        {"dish_code": 1, "spec": "单锅", "material_code": 200},
    ]
    fake_db = MagicMock()
    fake_db.fetchall.return_value = fake_rows
    with patch("inventory_check.db_bom.get_db", return_value=fake_db):
        rows = load_store_bom_rows("CA08")
    assert rows == fake_rows
    sql, params = fake_db.fetchall.call_args.args
    assert "FROM store_bom" in sql
    assert "WHERE werks = %s" in sql
    assert "ORDER BY dish_code, spec, material_code" in sql
    assert params == ("CA08",)


def test_load_store_bom_rows_raises_when_db_unavailable():
    with patch("inventory_check.db_bom.get_db", return_value=None):
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            load_store_bom_rows("CA08")
