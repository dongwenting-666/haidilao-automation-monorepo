"""Tests for the run guard (X-Run-Token / X-API-Key header enforcement).

NOTE: /api/commands route has been removed — all automation is triggered via
specific /api/reports/ endpoints or directly by the APScheduler cron jobs.
Auth is now ALWAYS required; there is no "allow all if unconfigured" fallback.
"""

from __future__ import annotations
from pathlib import Path

import pytest


class TestRunGuardEnabled:
    """Tests when RUN_TOKEN is set — all protected endpoints require the header."""

    def test_get_report_without_token_returns_403(self, unauthed_client, monkeypatch):
        import server.routes.reports as reports_mod
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = unauthed_client.get("/api/reports/daily/2026-03-18")
        assert resp.status_code == 403

    def test_get_report_with_token_allowed(self, client, mock_subprocess, monkeypatch):
        import server.routes.reports as reports_mod
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = client.get("/api/reports/daily/2026-03-18")
        assert resp.status_code == 202

    def test_status_endpoint_no_token_required(self, unauthed_client, monkeypatch):
        """Status endpoints are read-only — no token needed."""
        import server.routes.reports as reports_mod
        daily_dir = Path("/tmp/test-daily-status")
        daily_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
        resp = unauthed_client.get("/api/reports/daily/2026-03-18/status")
        assert resp.status_code == 200

    def test_list_runs_requires_token(self, unauthed_client):
        """GET /api/runs now requires auth."""
        resp = unauthed_client.get("/api/runs")
        assert resp.status_code == 403

    def test_list_runs_with_token_allowed(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_list_files_requires_token(self, unauthed_client):
        resp = unauthed_client.get("/api/files/")
        assert resp.status_code == 403

    def test_list_files_with_token_allowed(self, client, tmp_output):
        resp = client.get("/api/files/")
        assert resp.status_code == 200

    def test_treasury_check_without_token_returns_403(self, unauthed_client):
        resp = unauthed_client.post("/api/reports/treasury/check/2026-03-18")
        assert resp.status_code == 403

    def test_treasury_check_with_token_allowed(self, client, mock_subprocess):
        resp = client.post("/api/reports/treasury/check/2026-03-18")
        assert resp.status_code == 202

    def test_ksb1_without_token_returns_403(self, unauthed_client, monkeypatch):
        import server.routes.reports as reports_mod
        monkeypatch.setattr(reports_mod, "_KSB1_OUTPUT", Path("/nonexistent"))
        resp = unauthed_client.get("/api/reports/ksb1/2026/3")
        assert resp.status_code == 403

    def test_commands_route_removed(self, unauthed_client):
        """The /api/commands route no longer exists."""
        resp = unauthed_client.get("/api/commands")
        assert resp.status_code == 404
        resp2 = unauthed_client.post("/api/commands/daily-report/run", json={"params": {}})
        assert resp2.status_code == 404

    def test_docs_disabled(self, unauthed_client):
        """Public API docs are disabled."""
        assert unauthed_client.get("/docs").status_code == 404
        assert unauthed_client.get("/openapi.json").status_code == 404


class TestRunGuardAlwaysEnforced:
    """Auth is always required — no 'allow all if unconfigured' fallback."""

    @pytest.fixture(autouse=True)
    def _clear_token(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.run_token", "")

    def test_get_report_still_requires_auth(self, unauthed_client, monkeypatch):
        """Even with no RUN_TOKEN set, protected endpoints return 403."""
        import server.routes.reports as reports_mod
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = unauthed_client.get("/api/reports/daily/2026-03-18")
        assert resp.status_code == 403

    def test_list_runs_still_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/runs")
        assert resp.status_code == 403
