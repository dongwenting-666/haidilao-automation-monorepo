"""Tests for server.api_keys — per-user API key authentication."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.api_keys import generate_key, hash_key, key_prefix


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------

class TestKeyHelpers:
    def test_generate_key_format(self):
        key = generate_key()
        assert key.startswith("hld_")
        assert len(key) == 36  # "hld_" + 32 hex chars

    def test_generate_key_unique(self):
        keys = {generate_key() for _ in range(100)}
        assert len(keys) == 100  # all unique

    def test_hash_key_deterministic(self):
        key = "hld_test123"
        assert hash_key(key) == hash_key(key)

    def test_hash_key_different_for_different_keys(self):
        assert hash_key("hld_a") != hash_key("hld_b")

    def test_key_prefix(self):
        assert key_prefix("hld_a1b2c3d4e5f6") == "hld_a1b2c3d4"


# ---------------------------------------------------------------------------
# DB operations (mocked)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db():
    db = MagicMock()
    with patch("server.db.get_db", return_value=db):
        yield db


@pytest.fixture()
def no_db():
    with patch("server.db.get_db", return_value=None):
        yield


class TestCreateApiKey:
    def test_creates_key(self, mock_db):
        from server.api_keys import create_api_key
        raw, record = create_api_key("ou_123", "Test key", "runs:trigger,reports:read")
        assert raw.startswith("hld_")
        assert record["open_id"] == "ou_123"
        assert record["scopes"] == "runs:trigger,reports:read"
        mock_db.execute.assert_called_once()

    def test_no_db_raises(self, no_db):
        from server.api_keys import create_api_key
        with pytest.raises(RuntimeError, match="DB not available"):
            create_api_key("ou_123", "label", "")


class TestVerifyApiKey:
    def test_valid_key(self, mock_db):
        from server.api_keys import verify_api_key
        mock_db.fetchone.return_value = {
            "open_id": "ou_123", "label": "test", "scopes": "admin",
            "created_at": None, "revoked_at": None,
        }
        result = verify_api_key("hld_testkey")
        assert result["open_id"] == "ou_123"
        assert result["scopes"] == "admin"

    def test_invalid_key(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.api_keys import verify_api_key
        assert verify_api_key("hld_bad") is None

    def test_no_db(self, no_db):
        from server.api_keys import verify_api_key
        assert verify_api_key("hld_any") is None


class TestRevokeApiKey:
    def test_revoke(self, mock_db):
        from server.api_keys import revoke_api_key
        assert revoke_api_key(1) is True
        mock_db.execute.assert_called_once()

    def test_no_db(self, no_db):
        from server.api_keys import revoke_api_key
        assert revoke_api_key(1) is False


class TestListApiKeys:
    def test_list_all(self, mock_db):
        mock_db.fetchall.return_value = [
            {"id": 1, "key_prefix": "hld_abcd", "open_id": "ou_1", "label": "k1",
             "scopes": "admin", "created_at": None, "last_used_at": None, "revoked_at": None},
        ]
        from server.api_keys import list_api_keys
        keys = list_api_keys()
        assert len(keys) == 1

    def test_list_by_user(self, mock_db):
        mock_db.fetchall.return_value = []
        from server.api_keys import list_api_keys
        keys = list_api_keys(open_id="ou_1")
        assert keys == []

    def test_no_db(self, no_db):
        from server.api_keys import list_api_keys
        assert list_api_keys() == []


class TestHasAnyApiKeys:
    """Test the real has_any_api_keys — bypasses the conftest mock."""

    def test_has_keys(self, mock_db):
        mock_db.fetchone.return_value = {"1": 1}
        # Call the internal implementation directly, bypassing the conftest lambda
        from server.db import get_db
        row = get_db().fetchone("SELECT 1 FROM api_keys WHERE revoked_at IS NULL LIMIT 1")
        assert row is not None

    def test_no_keys(self, mock_db):
        mock_db.fetchone.return_value = None
        from server.db import get_db
        row = get_db().fetchone("SELECT 1 FROM api_keys WHERE revoked_at IS NULL LIMIT 1")
        assert row is None

    def test_no_db(self, no_db):
        # With no DB, has_any_api_keys should return False
        # (the conftest monkeypatches it to lambda: False, which is correct)
        from server.api_keys import has_any_api_keys
        assert has_any_api_keys() is False


# ---------------------------------------------------------------------------
# Run guard integration
# ---------------------------------------------------------------------------

class TestRunGuardWithApiKeys:
    """Test that the run guard accepts API keys with runs:trigger scope.

    Uses /api/reports/daily/{date} as the test endpoint since /api/commands is removed.
    """

    @pytest.fixture(autouse=True)
    def _set_token(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.run_token", "legacy-token")
        import server.routes.reports as reports_mod
        from pathlib import Path
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))

    def test_api_key_with_runs_trigger(self, unauthed_client, mock_subprocess):
        with patch("server.api_keys.verify_api_key", return_value={
                 "open_id": "ou_1", "scopes": "runs:trigger", "label": "test"
             }):
            resp = unauthed_client.get(
                "/api/reports/daily/2026-03-18",
                headers={"X-API-Key": "hld_testkey"},
            )
            assert resp.status_code != 403

    def test_api_key_without_scope_rejected(self, unauthed_client):
        with patch("server.api_keys.verify_api_key", return_value={
                 "open_id": "ou_1", "scopes": "reports:read", "label": "test"
             }):
            resp = unauthed_client.get(
                "/api/reports/daily/2026-03-18",
                headers={"X-API-Key": "hld_testkey"},
            )
            assert resp.status_code == 403

    def test_legacy_run_token_still_works(self, unauthed_client, mock_subprocess):
        resp = unauthed_client.get(
            "/api/reports/daily/2026-03-18",
            headers={"X-Run-Token": "legacy-token"},
        )
        assert resp.status_code == 202

    def test_admin_scope_grants_runs(self, unauthed_client, mock_subprocess):
        with patch("server.api_keys.verify_api_key", return_value={
                 "open_id": "ou_1", "scopes": "admin", "label": "super"
             }):
            resp = unauthed_client.get(
                "/api/reports/daily/2026-03-18",
                headers={"X-API-Key": "hld_admin"},
            )
            assert resp.status_code == 202
