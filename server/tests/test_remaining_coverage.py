"""Fill remaining coverage gaps across multiple modules."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# commands/store_hours_collect.py + treasury_loan_watch.py
# ---------------------------------------------------------------------------

class TestStoreHoursCommand:
    def test_build_args_default(self):
        from server.commands.store_hours_collect import StoreHoursCollectCommand
        cmd = StoreHoursCollectCommand()
        args = cmd.build_args({})
        assert "store_hours_collect.main" in " ".join(args)

    def test_build_args_with_date(self):
        from server.commands.store_hours_collect import StoreHoursCollectCommand
        cmd = StoreHoursCollectCommand()
        args = cmd.build_args({"date": "2026-03-18"})
        assert "2026-03-18" in args

    def test_name(self):
        from server.commands.store_hours_collect import StoreHoursCollectCommand
        assert StoreHoursCollectCommand().name == "store-hours-collect"


class TestTreasuryLoanWatchCommand:
    def test_build_args_default(self):
        from server.commands.treasury_loan_watch import TreasuryLoanWatchCommand
        cmd = TreasuryLoanWatchCommand()
        args = cmd.build_args({})
        assert "treasury_loan_watch.main" in " ".join(args)

    def test_build_args_with_date(self):
        from server.commands.treasury_loan_watch import TreasuryLoanWatchCommand
        cmd = TreasuryLoanWatchCommand()
        args = cmd.build_args({"date": "2026-03-18"})
        assert "2026-03-18" in args

    def test_name(self):
        from server.commands.treasury_loan_watch import TreasuryLoanWatchCommand
        assert TreasuryLoanWatchCommand().name == "treasury-loan-watch"


class TestKsb1Command:
    def test_build_args_with_month_year(self):
        from server.commands.ksb1 import KSB1Command
        cmd = KSB1Command()
        args = cmd.build_args({"month": 3, "year": 2026})
        assert "3" in args
        assert "2026" in args

    def test_build_args_skip_download(self):
        from server.commands.ksb1 import KSB1Command
        cmd = KSB1Command()
        args = cmd.build_args({"skip_download": True})
        assert "--skip-download" in args


# ---------------------------------------------------------------------------
# scheduler.py — async functions
# ---------------------------------------------------------------------------

class TestSchedulerFunctions:
    @pytest.mark.asyncio
    async def test_run_treasury_loan_watch(self):
        with patch("server.routes.runs.create_run") as mock:
            from server.scheduler import _run_treasury_loan_watch
            await _run_treasury_loan_watch()
            mock.assert_called_once_with("treasury-loan-watch", {}, notify_chat="hongming")

    @pytest.mark.asyncio
    async def test_run_store_hours_collect(self):
        with patch("server.routes.runs.create_run") as mock:
            from server.scheduler import _run_store_hours_collect
            await _run_store_hours_collect()
            # Run-complete card → hongming (admin). The store_hours group only
            # receives the unfilled-store alert sent directly by main.py.
            mock.assert_called_once_with("store-hours-collect", {}, notify_chat="hongming")


# ---------------------------------------------------------------------------
# routes/github_webhook.py — edge cases
# ---------------------------------------------------------------------------

class TestGithubWebhookEdgeCases:
    def test_webhook_no_secret_configured(self, client, monkeypatch):
        """When GITHUB_WEBHOOK_SECRET is empty, signature check is skipped."""
        monkeypatch.setattr("server.config.settings.github_webhook_secret", "")
        resp = client.post(
            "/api/github/webhook",
            json={"action": "opened", "issue": {"number": 1, "title": "Test"}},
            headers={"X-GitHub-Event": "issues"},
        )
        assert resp.status_code == 200

    def test_webhook_invalid_signature(self, client, monkeypatch):
        monkeypatch.setattr("server.config.settings.github_webhook_secret", "real-secret")
        resp = client.post(
            "/api/github/webhook",
            json={"action": "opened"},
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=wrong",
            },
        )
        assert resp.status_code == 401

    def test_webhook_irrelevant_event(self, client, monkeypatch):
        monkeypatch.setattr("server.config.settings.github_webhook_secret", "")
        resp = client.post(
            "/api/github/webhook",
            json={"action": "assigned"},
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# routes/reports.py — run guard on GET endpoints
# ---------------------------------------------------------------------------

class TestReportsRunGuard:
    def test_daily_report_existing_file_no_token_needed(self, client, tmp_path, monkeypatch):
        """If the file already exists, it's served directly — no run created, no guard."""
        import server.routes.reports as reports_mod
        daily_dir = tmp_path / "daily-report"
        daily_dir.mkdir()
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"fake-excel")
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
        monkeypatch.setattr("server.config.settings.run_token", "secret")
        # Even with run_token set, existing file should be served (200, not 403)
        resp = client.get(
            "/api/reports/daily/2026-03-18",
            headers={"X-Run-Token": "secret"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# notify.py — _client() returns None
# ---------------------------------------------------------------------------

class TestNotifyClientNone:
    def test_notify_run_complete_client_none(self, monkeypatch):
        """When _client() returns None, notification is silently skipped."""
        monkeypatch.setattr("server.config.settings.lark_app_id", "id")
        monkeypatch.setattr("server.config.settings.lark_app_secret", "secret")

        from server.notify import _load_config
        _load_config.cache_clear()
        from lark_client.notify_config import _load_chats
        _load_chats.cache_clear()

        with patch("server.notify._client", return_value=None), \
             patch("server.notify._target_for", return_value=("oc_test", None)):
            from server.notify import notify_run_complete
            run = MagicMock()
            run.command = "daily-report"
            run.status.value = "success"
            run.logs = "test"
            run.id = "run1"
            run.started_at = None
            run.finished_at = None
            notify_run_complete(run)  # should not raise
