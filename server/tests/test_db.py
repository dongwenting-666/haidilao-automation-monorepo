"""Tests for server.db — DB layer with mock database."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_db():
    """Reset DB singleton between tests."""
    import server.db as db_mod
    db_mod._db = None
    db_mod._db_attempted = False
    yield
    db_mod._db = None
    db_mod._db_attempted = False


@pytest.fixture()
def mock_db():
    """Provide a mock Database and inject it as the singleton."""
    import server.db as db_mod
    db = MagicMock()
    db_mod._db = db
    db_mod._db_attempted = True
    return db


@pytest.fixture()
def no_db(monkeypatch):
    """Ensure no DB is available."""
    monkeypatch.setattr("server.config.settings.database_url", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)


# ---------------------------------------------------------------------------
# get_db / is_db_available
# ---------------------------------------------------------------------------

class TestGetDb:
    def test_returns_none_when_no_url(self, no_db):
        from server.db import get_db
        assert get_db() is None

    def test_caches_result(self, no_db):
        from server.db import get_db
        get_db()
        get_db()  # second call should use cache

    def test_is_db_available_false_when_no_url(self, no_db):
        from server.db import is_db_available
        assert is_db_available() is False

    def test_is_db_available_true_with_mock(self, mock_db):
        from server.db import is_db_available
        assert is_db_available() is True


# ---------------------------------------------------------------------------
# Targets CRUD
# ---------------------------------------------------------------------------

class TestTargets:
    def test_get_targets_with_data(self, mock_db):
        mock_db.fetchall.return_value = [
            {"store_name": "Store1", "revenue": "100.5",
             "tr_slot_1": "1.0", "tr_slot_2": "1.5", "tr_slot_3": "2.0",
             "tr_slot_4": "0.5", "tr_total": "5.0"},
        ]
        from server.db import get_targets
        result = get_targets("2026-03")
        assert result["revenue"]["Store1"] == 100.5
        assert result["turnover_rate"]["Store1"]["total"] == 5.0

    def test_get_targets_no_db(self, no_db):
        from server.db import get_targets
        result = get_targets("2026-03")
        assert result == {"revenue": {}, "turnover_rate": {}}

    def test_set_targets(self, mock_db):
        from server.db import set_targets
        set_targets("2026-03", "Store1", 100, 1, 1.5, 2, 0.5, 5)
        mock_db.execute.assert_called_once()

    def test_set_targets_no_db(self, no_db):
        from server.db import set_targets
        with pytest.raises(RuntimeError, match="DB not available"):
            set_targets("2026-03", "Store1", 100, 1, 1.5, 2, 0.5, 5)

    def test_has_targets_true(self, mock_db):
        mock_db.fetchone.return_value = {"1": 1}
        from server.db import has_targets
        assert has_targets("2026-03") is True

    def test_has_targets_false(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import has_targets
        assert has_targets("2026-03") is False

    def test_has_targets_no_db(self, no_db):
        from server.db import has_targets
        assert has_targets("2026-03") is False

    def test_get_all_months(self, mock_db):
        mock_db.fetchall.return_value = [{"month_key": "2026-03"}, {"month_key": "2026-02"}]
        from server.db import get_all_months
        assert get_all_months() == ["2026-03", "2026-02"]

    def test_get_all_months_no_db(self, no_db):
        from server.db import get_all_months
        assert get_all_months() == []


# ---------------------------------------------------------------------------
# Competitors CRUD
# ---------------------------------------------------------------------------

class TestCompetitors:
    def test_get_competitors(self, mock_db):
        mock_db.fetchall.return_value = [
            {"store_name": "Store1", "competitor_name": "Comp1"},
        ]
        from server.db import get_competitors
        assert get_competitors() == {"Store1": "Comp1"}

    def test_get_competitors_no_db(self, no_db):
        from server.db import get_competitors
        assert get_competitors() == {}

    def test_set_competitor(self, mock_db):
        from server.db import set_competitor
        set_competitor("Store1", "Comp1")
        mock_db.execute.assert_called_once()

    def test_set_competitor_no_db(self, no_db):
        from server.db import set_competitor
        with pytest.raises(RuntimeError):
            set_competitor("Store1", "Comp1")

    def test_has_competitors_true(self, mock_db):
        mock_db.fetchone.return_value = {"1": 1}
        from server.db import has_competitors
        assert has_competitors() is True

    def test_has_competitors_false(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import has_competitors
        assert has_competitors() is False

    def test_has_competitors_no_db(self, no_db):
        from server.db import has_competitors
        assert has_competitors() is False


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

class TestReportHelpers:
    def test_get_targets_for_report_no_db(self, no_db):
        from server.db import get_targets_for_report
        result = get_targets_for_report("2026-03")
        assert result == {"revenue": {}, "turnover_rate": {}}

    def test_get_competitor_for_report_no_db(self, no_db):
        from server.db import get_competitor_for_report
        assert get_competitor_for_report() == {}

    def test_get_targets_for_report_with_db(self, mock_db):
        mock_db.fetchall.return_value = []
        from server.db import get_targets_for_report
        result = get_targets_for_report("2026-03")
        assert result == {"revenue": {}, "turnover_rate": {}}


# ---------------------------------------------------------------------------
# Admin users
# ---------------------------------------------------------------------------

class TestAdminUsers:
    def test_upsert_admin_user(self, mock_db):
        from server.db import upsert_admin_user
        upsert_admin_user("ou_123", "Alice", "https://avatar.url")
        mock_db.execute.assert_called_once()

    def test_upsert_admin_user_no_db(self, no_db):
        from server.db import upsert_admin_user
        upsert_admin_user("ou_123", "Alice")  # should not raise

    def test_is_db_whitelisted_true(self, mock_db):
        mock_db.fetchone.return_value = {"whitelisted": True}
        from server.db import is_db_whitelisted
        assert is_db_whitelisted("ou_123") is True

    def test_is_db_whitelisted_false(self, mock_db):
        mock_db.fetchone.return_value = {"whitelisted": False}
        from server.db import is_db_whitelisted
        assert is_db_whitelisted("ou_123") is False

    def test_is_db_whitelisted_not_found(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import is_db_whitelisted
        assert is_db_whitelisted("ou_123") is False

    def test_is_db_whitelisted_no_db(self, no_db):
        from server.db import is_db_whitelisted
        assert is_db_whitelisted("ou_123") is False

    def test_set_admin_whitelist(self, mock_db):
        from server.db import set_admin_whitelist
        set_admin_whitelist("ou_123", True)
        mock_db.execute.assert_called_once()

    def test_set_admin_whitelist_no_db(self, no_db):
        from server.db import set_admin_whitelist
        with pytest.raises(RuntimeError):
            set_admin_whitelist("ou_123", True)

    def test_get_admin_users(self, mock_db):
        mock_db.fetchall.return_value = [{"open_id": "ou_123", "name": "Alice"}]
        from server.db import get_admin_users
        assert len(get_admin_users()) == 1

    def test_get_admin_users_no_db(self, no_db):
        from server.db import get_admin_users
        assert get_admin_users() == []


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_maybe_run_migrations_no_db(self, no_db):
        from server.db import maybe_run_migrations
        maybe_run_migrations()  # should not raise

    def test_maybe_run_migrations_with_db(self, mock_db):
        with patch("db_client.migrations.run_migrations") as mock_run:
            from server.db import maybe_run_migrations
            maybe_run_migrations()
            mock_run.assert_called_once()

    def test_maybe_run_migrations_exception(self, mock_db):
        with patch("db_client.migrations.run_migrations", side_effect=Exception("fail")):
            from server.db import maybe_run_migrations
            maybe_run_migrations()  # should not raise

    def test_migrate_from_json_no_db(self, no_db, tmp_path):
        from server.db import migrate_from_json
        migrate_from_json(tmp_path / "t.json", tmp_path / "c.json")  # should not raise

    def test_migrate_from_json_missing_files(self, mock_db, tmp_path):
        from server.db import migrate_from_json
        migrate_from_json(tmp_path / "nonexistent.json", tmp_path / "nonexistent2.json")
        # Should log warnings but not raise

    def test_migrate_from_json_with_data(self, mock_db, tmp_path):
        import json
        targets = {"2026-03": {"revenue": {"Store1": 100}, "turnover_rate": {"Store1": {"total": 5}}}}
        comps = {"Store1": "Comp1"}
        (tmp_path / "targets.json").write_text(json.dumps(targets))
        (tmp_path / "comps.json").write_text(json.dumps(comps))
        mock_db.fetchone.return_value = None  # no existing entries
        from server.db import migrate_from_json
        migrate_from_json(tmp_path / "targets.json", tmp_path / "comps.json")
        assert mock_db.execute.call_count >= 2  # at least target + competitor inserts


# ── Store BOM ─────────────────────────────────────────────────────────────────


class TestStoreBom:
    def test_list_bom_werks_empty_when_no_db(self, no_db):
        from server.db import list_bom_werks
        assert list_bom_werks() == []

    def test_list_bom_werks(self, mock_db):
        mock_db.fetchall.return_value = [{"werks": "CA01"}, {"werks": "CA08"}]
        from server.db import list_bom_werks
        assert list_bom_werks() == ["CA01", "CA08"]

    def test_list_bom_empty_when_no_db(self, no_db):
        from server.db import list_bom
        assert list_bom("CA08") == []

    def test_list_bom_basic_filter(self, mock_db):
        mock_db.fetchall.return_value = [{"id": 1, "dish_code": 1060061}]
        from server.db import list_bom
        rows = list_bom("CA08", dish_filter="清油", limit=10)
        assert len(rows) == 1
        # SQL must include the dish-filter clause and the werks param
        args = mock_db.fetchall.call_args
        sql = args[0][0]
        params = args[0][1]
        assert "werks = %s" in sql
        assert "ILIKE %s" in sql
        assert params[0] == "CA08"
        assert "%清油%" in params

    def test_list_bom_with_material_filter(self, mock_db):
        mock_db.fetchall.return_value = []
        from server.db import list_bom
        list_bom("CA08", material_filter="3000759")
        sql = mock_db.fetchall.call_args[0][0]
        params = mock_db.fetchall.call_args[0][1]
        assert "material_name" in sql or "material_code" in sql
        assert "%3000759%" in params

    def test_count_bom(self, mock_db):
        mock_db.fetchone.return_value = {"n": 42}
        from server.db import count_bom
        assert count_bom("CA08") == 42
        sql = mock_db.fetchone.call_args[0][0]
        assert "COUNT(*)" in sql

    def test_get_bom_entry_no_db(self, no_db):
        from server.db import get_bom_entry
        assert get_bom_entry(1) is None

    def test_get_bom_entry(self, mock_db):
        mock_db.fetchone.return_value = {"id": 5, "werks": "CA08", "dish_code": 1060061}
        from server.db import get_bom_entry
        out = get_bom_entry(5)
        assert out["dish_code"] == 1060061
        # Param-binding: id should be the only param
        assert mock_db.fetchone.call_args[0][1] == (5,)

    def test_upsert_bom_entry_insert_returns_id(self, mock_db):
        mock_db.fetchone.return_value = {"id": 7}
        from server.db import upsert_bom_entry
        new_id = upsert_bom_entry(
            "CA08", 1060061, "单锅", 3000759,
            dish_name="清油麻辣火锅", portion=1.2, loss_factor=1.0,
        )
        assert new_id == 7
        sql = mock_db.fetchone.call_args[0][0]
        # INSERT path uses ON CONFLICT — no entry_id given.
        assert "INSERT INTO store_bom" in sql
        assert "ON CONFLICT" in sql

    def test_upsert_bom_entry_update_path(self, mock_db):
        mock_db.fetchone.return_value = {"id": 7}
        from server.db import upsert_bom_entry
        new_id = upsert_bom_entry(
            "CA08", 1060061, "单锅", 3000759,
            entry_id=7, dish_name="清油麻辣火锅",
        )
        assert new_id == 7
        # UPDATE path when entry_id given
        sql = mock_db.fetchone.call_args[0][0]
        assert sql.lstrip().startswith("UPDATE store_bom")

    def test_upsert_bom_entry_update_missing_raises(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import upsert_bom_entry
        with pytest.raises(ValueError, match="not found"):
            upsert_bom_entry("CA08", 1, None, 1, entry_id=999)

    def test_upsert_bom_entry_no_db_raises(self, no_db):
        from server.db import upsert_bom_entry
        with pytest.raises(RuntimeError, match="DB not available"):
            upsert_bom_entry("CA08", 1, None, 1)

    def test_delete_bom_entry_true(self, mock_db):
        mock_db.fetchone.return_value = {"id": 5}
        from server.db import delete_bom_entry
        assert delete_bom_entry(5) is True

    def test_delete_bom_entry_missing(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import delete_bom_entry
        assert delete_bom_entry(999) is False

    def test_delete_bom_entry_no_db(self, no_db):
        from server.db import delete_bom_entry
        assert delete_bom_entry(1) is False
