"""Tests for server.notify — Lark notification helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear lru_cache between tests so monkeypatch takes effect."""
    from server.notify import _load_config
    from lark_client.notify_config import _load_chats
    _load_config.cache_clear()
    _load_chats.cache_clear()
    yield
    _load_config.cache_clear()
    _load_chats.cache_clear()


@pytest.fixture()
def sample_toml(tmp_path, monkeypatch):
    """Write a sample notify.toml and point both modules at it."""
    toml_file = tmp_path / "notify.toml"
    toml_file.write_text("""
[chats]
hongming = "oc_test_hongming"
production = "oc_test_production"

[daily-report]
chat = "hongming"

[treasury-loan-watch]
chat_id = "oc_raw_id"

[both-set]
chat_id = "oc_chat"
user_id = "ou_user"
""")
    import server.notify as notify_mod
    monkeypatch.setattr(notify_mod, "_NOTIFY_CONFIG", toml_file)

    import lark_client.notify_config as nc_mod
    monkeypatch.setattr(nc_mod, "_load_chats", lambda: {"hongming": "oc_test_hongming", "production": "oc_test_production"})
    return toml_file


@pytest.fixture()
def mock_lark_client():
    """Mock _client() to return a MagicMock LarkClient."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    with patch("server.notify._client", return_value=mock):
        yield mock


@pytest.fixture()
def lark_enabled(monkeypatch):
    """Ensure lark_enabled returns True."""
    monkeypatch.setattr("server.config.settings.lark_app_id", "test_id")
    monkeypatch.setattr("server.config.settings.lark_app_secret", "test_secret")


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_load_config_returns_dict(self, sample_toml):
        from server.notify import _load_config
        config = _load_config()
        assert "daily-report" in config
        assert config["chats"]["hongming"] == "oc_test_hongming"

    def test_load_config_missing_file(self, tmp_path, monkeypatch):
        import server.notify as notify_mod
        monkeypatch.setattr(notify_mod, "_NOTIFY_CONFIG", tmp_path / "nonexistent.toml")
        from server.notify import _load_config
        _load_config.cache_clear()
        assert _load_config() == {}

    def test_load_config_invalid_toml(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.toml"
        bad.write_text("not valid toml [[[")
        import server.notify as notify_mod
        monkeypatch.setattr(notify_mod, "_NOTIFY_CONFIG", bad)
        from server.notify import _load_config
        _load_config.cache_clear()
        assert _load_config() == {}


# ---------------------------------------------------------------------------
# _target_for
# ---------------------------------------------------------------------------

class TestTargetFor:
    def test_alias_resolution(self, sample_toml):
        from server.notify import _target_for
        chat_id, user_id, _ = _target_for("daily-report")
        assert chat_id == "oc_test_hongming"
        assert user_id is None

    def test_raw_chat_id_fallback(self, sample_toml):
        from server.notify import _target_for
        chat_id, user_id, _ = _target_for("treasury-loan-watch")
        assert chat_id == "oc_raw_id"
        assert user_id is None

    def test_both_set_prefers_chat_id(self, sample_toml):
        from server.notify import _target_for
        chat_id, user_id, _ = _target_for("both-set")
        assert chat_id == "oc_chat"
        assert user_id is None

    def test_unknown_command_returns_none(self, sample_toml):
        from server.notify import _target_for
        chat_id, user_id, _ = _target_for("nonexistent-command")
        assert chat_id is None
        assert user_id is None

    def test_unknown_alias_returns_none(self, tmp_path, monkeypatch):
        toml_file = tmp_path / "notify.toml"
        toml_file.write_text('[chats]\n\n[test]\nchat = "does_not_exist"\n')
        import server.notify as notify_mod
        monkeypatch.setattr(notify_mod, "_NOTIFY_CONFIG", toml_file)
        import lark_client.notify_config as nc_mod
        monkeypatch.setattr(nc_mod, "_load_chats", lambda: {})
        from server.notify import _load_config, _target_for
        _load_config.cache_clear()
        chat_id, _, _2 = _target_for("test")
        assert chat_id is None


# ---------------------------------------------------------------------------
# chat_id_for
# ---------------------------------------------------------------------------

class TestChatIdFor:
    def test_resolves_known_alias(self, sample_toml):
        from server.notify import chat_id_for
        assert chat_id_for("hongming") == "oc_test_hongming"

    def test_returns_none_for_unknown(self, sample_toml):
        from server.notify import chat_id_for
        assert chat_id_for("nonexistent") is None


# ---------------------------------------------------------------------------
# notify_run_complete
# ---------------------------------------------------------------------------

class TestNotifyRunComplete:
    def _make_run(self, command="daily-report", status="success", logs="test output"):
        from datetime import datetime, timezone, timedelta
        run = MagicMock()
        run.command = command
        run.status.value = status
        run.logs = logs
        run.id = "test-run-123"
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        run.finished_at = datetime.now(timezone.utc)
        return run

    def test_sends_card_on_success(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_run_complete
        run = self._make_run()
        notify_run_complete(run)
        mock_lark_client.send_card.assert_called_once()
        call_kwargs = mock_lark_client.send_card.call_args.kwargs
        assert call_kwargs["color"] == "green"
        assert call_kwargs["chat_id"] == "oc_test_hongming"

    def test_sends_red_card_on_failure(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_run_complete
        run = self._make_run(status="failed")
        notify_run_complete(run)
        call_kwargs = mock_lark_client.send_card.call_args.kwargs
        assert call_kwargs["color"] == "red"

    def test_skips_when_lark_disabled(self, sample_toml, monkeypatch):
        monkeypatch.setattr("server.config.settings.lark_app_id", "")
        from server.notify import notify_run_complete
        run = self._make_run()
        notify_run_complete(run)  # should not raise

    def test_skips_when_no_target(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_run_complete
        run = self._make_run(command="unknown-command")
        notify_run_complete(run)
        mock_lark_client.send_card.assert_not_called()

    def test_handles_no_logs(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_run_complete
        run = self._make_run(logs="")
        notify_run_complete(run)
        mock_lark_client.send_card.assert_called_once()

    def test_handles_send_exception(self, sample_toml, mock_lark_client, lark_enabled):
        mock_lark_client.send_card.side_effect = Exception("network error")
        from server.notify import notify_run_complete
        run = self._make_run()
        notify_run_complete(run)  # should not raise


# ---------------------------------------------------------------------------
# notify_daily_report_file
# ---------------------------------------------------------------------------

class TestNotifyDailyReportFile:
    def test_sends_card_and_file(self, sample_toml, mock_lark_client, lark_enabled, tmp_path, monkeypatch):
        import lark_client.notify_config as nc_mod
        monkeypatch.setattr(nc_mod, "_load_chats", lambda: {
            "hongming": "oc_test_hongming",
            "production_accounting_report_chat": "oc_test_production",
        })
        report = tmp_path / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"fake-excel")
        from server.notify import notify_daily_report_file
        notify_daily_report_file(report)
        mock_lark_client.send_card.assert_called_once()
        mock_lark_client.send_file.assert_called_once()
        assert "2026-03-18" in mock_lark_client.send_card.call_args.kwargs["title"]

    def test_skips_when_lark_disabled(self, sample_toml, monkeypatch, tmp_path):
        monkeypatch.setattr("server.config.settings.lark_app_id", "")
        report = tmp_path / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"fake")
        from server.notify import notify_daily_report_file
        notify_daily_report_file(report)  # should not raise

    def test_skips_when_alias_missing(self, sample_toml, mock_lark_client, lark_enabled, tmp_path):
        # sample_toml doesn't have production_accounting_report_chat
        report = tmp_path / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"fake")
        from server.notify import notify_daily_report_file
        notify_daily_report_file(report)
        mock_lark_client.send_card.assert_not_called()

    def test_handles_send_exception(self, sample_toml, mock_lark_client, lark_enabled, tmp_path, monkeypatch):
        import lark_client.notify_config as nc_mod
        monkeypatch.setattr(nc_mod, "_load_chats", lambda: {
            "production_accounting_report_chat": "oc_test_production",
        })
        mock_lark_client.send_card.side_effect = Exception("boom")
        report = tmp_path / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"fake")
        from server.notify import notify_daily_report_file
        notify_daily_report_file(report)  # should not raise

    def test_unknown_date_in_filename(self, sample_toml, mock_lark_client, lark_enabled, tmp_path, monkeypatch):
        import lark_client.notify_config as nc_mod
        monkeypatch.setattr(nc_mod, "_load_chats", lambda: {
            "production_accounting_report_chat": "oc_test",
        })
        report = tmp_path / "weird_report.xlsx"
        report.write_bytes(b"fake")
        from server.notify import notify_daily_report_file
        notify_daily_report_file(report)
        assert "unknown date" in mock_lark_client.send_card.call_args.kwargs["title"]


# ---------------------------------------------------------------------------
# notify_text
# ---------------------------------------------------------------------------

class TestNotifyText:
    def test_sends_text(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_text
        notify_text("daily-report", "Hello")
        mock_lark_client.send_text.assert_called_once_with(
            "Hello", chat_id="oc_test_hongming", user_id=None
        )

    def test_skips_when_no_target(self, sample_toml, mock_lark_client, lark_enabled):
        from server.notify import notify_text
        notify_text("nonexistent", "Hello")
        mock_lark_client.send_text.assert_not_called()

    def test_skips_when_lark_disabled(self, sample_toml, monkeypatch):
        monkeypatch.setattr("server.config.settings.lark_app_id", "")
        from server.notify import notify_text
        notify_text("daily-report", "Hello")  # no error

    def test_handles_exception(self, sample_toml, mock_lark_client, lark_enabled):
        mock_lark_client.send_text.side_effect = Exception("fail")
        from server.notify import notify_text
        notify_text("daily-report", "Hello")  # should not raise
