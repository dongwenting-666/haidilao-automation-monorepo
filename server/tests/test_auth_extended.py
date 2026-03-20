"""Extended auth tests — OAuth flow, whitelist edge cases, super admin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestIsWhitelisted:
    def test_db_whitelisted(self, monkeypatch):
        with patch("server.db.is_db_whitelisted", return_value=True):
            from server.auth import is_whitelisted
            assert is_whitelisted("ou_123") is True

    def test_db_not_whitelisted_env_fallback(self, monkeypatch):
        with patch("server.db.is_db_whitelisted", return_value=False):
            monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_123,ou_456")
            from server.auth import is_whitelisted
            assert is_whitelisted("ou_123") is True

    def test_not_whitelisted_anywhere(self, monkeypatch):
        with patch("server.db.is_db_whitelisted", return_value=False):
            monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_other")
            from server.auth import is_whitelisted
            assert is_whitelisted("ou_123") is False

    def test_empty_whitelist(self, monkeypatch):
        with patch("server.db.is_db_whitelisted", return_value=False):
            monkeypatch.setattr("server.config.settings.admin_whitelist", "")
            from server.auth import is_whitelisted
            assert is_whitelisted("ou_123") is False

    def test_db_exception_falls_through(self, monkeypatch):
        with patch("server.db.is_db_whitelisted", side_effect=Exception("db down")):
            monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_123")
            from server.auth import is_whitelisted
            assert is_whitelisted("ou_123") is True


class TestIsSuperAdmin:
    def test_in_super_admin_list(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "ou_admin1,ou_admin2")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "")
        from server.auth import is_super_admin
        assert is_super_admin("ou_admin1") is True

    def test_fallback_to_admin_whitelist(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_fallback")
        from server.auth import is_super_admin
        assert is_super_admin("ou_fallback") is True

    def test_not_super_admin(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "ou_admin")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "")
        from server.auth import is_super_admin
        assert is_super_admin("ou_other") is False

    def test_empty_both(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "")
        from server.auth import is_super_admin
        assert is_super_admin("ou_any") is False


class TestLarkCredentials:
    def test_get_credentials_from_settings(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.lark_app_id", "test_id")
        monkeypatch.setattr("server.config.settings.lark_app_secret", "test_secret")
        from server.auth import _get_lark_credentials
        app_id, app_secret = _get_lark_credentials()
        assert app_id == "test_id"
        assert app_secret == "test_secret"


class TestGetLarkAuthUrl:
    def test_builds_url(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.lark_app_id", "test_app_id")
        monkeypatch.setattr("server.config.settings.lark_app_secret", "test_secret")
        from server.auth import get_lark_auth_url
        url = get_lark_auth_url("https://example.com/callback", "test-state")
        assert "test_app_id" in url
        assert "test-state" in url
        assert "authorize" in url


class TestGetRedirectUri:
    def test_from_settings(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.lark_oauth_redirect_uri", "https://custom.url/callback")
        from server.routes.admin import _get_redirect_uri
        assert _get_redirect_uri() == "https://custom.url/callback"


class TestSessionCookie:
    def test_clear_session_cookie(self):
        from unittest.mock import MagicMock
        from server.auth import clear_session_cookie
        resp = MagicMock()
        clear_session_cookie(resp)
        resp.delete_cookie.assert_called_once()

    def test_get_session_invalid_cookie(self):
        from server.auth import get_session
        from unittest.mock import MagicMock
        request = MagicMock()
        request.cookies.get.return_value = "invalid-signed-data"
        assert get_session(request) is None

    def test_get_session_no_cookie(self):
        from server.auth import get_session
        from unittest.mock import MagicMock
        request = MagicMock()
        request.cookies.get.return_value = None
        assert get_session(request) is None
