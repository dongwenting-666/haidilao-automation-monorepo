"""Tests for new Settings fields and properties added on 2026-03-20."""

from __future__ import annotations

import pytest


class TestSettingsProperties:
    def test_cookie_secure_bool_defaults_true(self):
        from server.config import Settings
        s = Settings(lark_app_id="x", lark_app_secret="y")
        assert s.cookie_secure_bool is True

    def test_cookie_secure_bool_false_for_false(self):
        from server.config import Settings
        s = Settings(cookie_secure="false", lark_app_id="x", lark_app_secret="y")
        assert s.cookie_secure_bool is False

    def test_cookie_secure_bool_false_for_zero(self):
        from server.config import Settings
        s = Settings(cookie_secure="0", lark_app_id="x", lark_app_secret="y")
        assert s.cookie_secure_bool is False

    def test_cookie_secure_bool_false_for_no(self):
        from server.config import Settings
        s = Settings(cookie_secure="no", lark_app_id="x", lark_app_secret="y")
        assert s.cookie_secure_bool is False

    def test_minio_secure_bool_defaults_false(self):
        from server.config import Settings
        s = Settings(lark_app_id="x", lark_app_secret="y")
        assert s.minio_secure_bool is False

    def test_minio_secure_bool_true_for_true(self):
        from server.config import Settings
        s = Settings(minio_secure="true", lark_app_id="x", lark_app_secret="y")
        assert s.minio_secure_bool is True

    def test_lark_enabled_when_both_set(self):
        from server.config import Settings
        s = Settings(lark_app_id="id", lark_app_secret="secret")
        assert s.lark_enabled is True

    def test_lark_disabled_when_missing(self):
        from server.config import Settings
        s = Settings(lark_app_id="", lark_app_secret="")
        assert s.lark_enabled is False

    def test_database_url_default_empty(self):
        from server.config import Settings
        s = Settings(lark_app_id="x", lark_app_secret="y")
        assert s.database_url == ""

    def test_github_webhook_secret_default_empty(self):
        from server.config import Settings
        s = Settings(lark_app_id="x", lark_app_secret="y")
        assert s.github_webhook_secret == ""

    def test_all_minio_defaults(self):
        from server.config import Settings
        s = Settings(lark_app_id="x", lark_app_secret="y")
        assert s.minio_endpoint == "localhost:9000"
        assert s.minio_root_user == "haidilao"
        assert s.minio_root_password == "haidilao_minio_dev"
        assert s.minio_bucket == "tools-uploads"
