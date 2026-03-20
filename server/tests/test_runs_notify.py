"""Tests for _notify_run and _find_report_from_run in server.routes.runs."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def daily_dir(tmp_path, monkeypatch):
    """Create a temp daily-report output dir and point settings at it."""
    d = tmp_path / "daily-report"
    d.mkdir()
    import server.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "output_dir", tmp_path)
    return d


@pytest.fixture()
def make_run():
    """Factory for Run-like objects."""
    def _make(command="daily-report", status="success", params=None, logs=None):
        from server.routes.runs import RunStatus
        run = MagicMock()
        run.command = command
        run.status = RunStatus.SUCCESS if status == "success" else RunStatus.FAILED
        run.params = params or {}
        run.logs = logs
        run.id = "test-run"
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        run.finished_at = datetime.now(timezone.utc)
        run.notify_chat = ""  # default: no file delivery
        return run
    return _make


# ---------------------------------------------------------------------------
# _find_report_from_run
# ---------------------------------------------------------------------------

class TestFindReportFromRun:
    def test_strategy_1_explicit_date(self, daily_dir, make_run):
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        from server.routes.runs import _find_report_from_run
        run = make_run(params={"date": "2026-03-18"})
        assert _find_report_from_run(run) == report

    def test_strategy_1_date_not_found(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run(params={"date": "2099-01-01"})
        assert _find_report_from_run(run) is None

    def test_strategy_1_invalid_date(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run(params={"date": "not-a-date"})
        assert _find_report_from_run(run) is None

    def test_strategy_2_parse_logs(self, daily_dir, make_run):
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        from server.routes.runs import _find_report_from_run
        run = make_run(logs=f"INFO Report saved to {report}")
        assert _find_report_from_run(run) == report

    def test_strategy_2_log_path_not_exists(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run(logs="Report saved to /nonexistent/database_report_2026_01_01.xlsx")
        # Falls through to strategy 3
        assert _find_report_from_run(run) is None

    def test_strategy_3_most_recent(self, daily_dir, make_run):
        import time
        old = daily_dir / "database_report_2026_01_01.xlsx"
        old.write_bytes(b"old")
        time.sleep(0.05)
        new = daily_dir / "database_report_2026_03_18.xlsx"
        new.write_bytes(b"new")
        from server.routes.runs import _find_report_from_run
        run = make_run()  # no params, no logs
        assert _find_report_from_run(run) == new

    def test_strategy_3_empty_dir(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run()
        assert _find_report_from_run(run) is None

    def test_none_logs(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run(logs=None)
        assert _find_report_from_run(run) is None

    def test_empty_logs(self, daily_dir, make_run):
        from server.routes.runs import _find_report_from_run
        run = make_run(logs="")
        assert _find_report_from_run(run) is None


# ---------------------------------------------------------------------------
# _notify_run
# ---------------------------------------------------------------------------

class TestNotifyRun:
    def test_calls_notify_run_complete(self, make_run):
        run = make_run(command="ksb1")
        run.notify_chat = "hongming"  # must be set to get notifications
        with patch("server.notify.notify_run_complete") as mock:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock.assert_called_once_with(run)

    def test_empty_notify_chat_skips_all_notifications(self, make_run):
        """No notify_chat = completely silent — no card, no file."""
        run = make_run(command="daily-report", status="success")
        run.notify_chat = ""
        with patch("server.notify.notify_run_complete") as mock_card, \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_card.assert_not_called()
            mock_file.assert_not_called()

    def test_with_notify_chat_sends_file_to_target(self, daily_dir, make_run):
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        run = make_run(
            command="daily-report",
            status="success",
            logs=f"Report saved to {report}",
        )
        run.notify_chat = "production_accounting_report_chat"
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_called_once_with(report, target_chat="production_accounting_report_chat")

    def test_custom_notify_chat_sends_to_custom_target(self, daily_dir, make_run):
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        run = make_run(
            command="daily-report",
            status="success",
            logs=f"Report saved to {report}",
        )
        run.notify_chat = "hongming"
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_called_once_with(report, target_chat="hongming")

    def test_empty_notify_chat_no_file_send(self, daily_dir, make_run):
        """No notify_chat = no file delivery (manual/test runs)."""
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        run = make_run(
            command="daily-report",
            status="success",
            logs=f"Report saved to {report}",
        )
        run.notify_chat = ""
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_not_called()

    def test_daily_report_failure_no_file_send(self, daily_dir, make_run):
        run = make_run(command="daily-report", status="failed")
        run.notify_chat = "production_accounting_report_chat"
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_not_called()

    def test_non_daily_report_no_file_send(self, make_run):
        run = make_run(command="ksb1", status="success")
        run.notify_chat = "production_accounting_report_chat"
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_not_called()

    def test_notify_exception_swallowed(self, make_run):
        run = make_run(command="daily-report")
        run.notify_chat = "hongming"
        with patch("server.notify.notify_run_complete", side_effect=Exception("boom")):
            from server.routes.runs import _notify_run
            _notify_run(run)  # should not raise

    def test_file_send_exception_swallowed(self, daily_dir, make_run):
        report = daily_dir / "database_report_2026_03_18.xlsx"
        report.write_bytes(b"excel")
        run = make_run(
            command="daily-report",
            status="success",
            logs=f"Report saved to {report}",
        )
        run.notify_chat = "production_accounting_report_chat"
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file", side_effect=Exception("boom")):
            from server.routes.runs import _notify_run
            _notify_run(run)  # should not raise

    def test_no_report_found_skips_file_send(self, daily_dir, make_run):
        run = make_run(command="daily-report", status="success")
        run.notify_chat = "production_accounting_report_chat"
        # Empty daily_dir — no files to find
        with patch("server.notify.notify_run_complete"), \
             patch("server.notify.notify_daily_report_file") as mock_file:
            from server.routes.runs import _notify_run
            _notify_run(run)
            mock_file.assert_not_called()
