"""Tests for the run guard (X-Run-Token header enforcement)."""

from __future__ import annotations

import pytest


class TestRunGuardEnabled:
    """Tests when RUN_TOKEN is set — all run-triggering endpoints require the header."""

    @pytest.fixture(autouse=True)
    def _set_token(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.run_token", "test-secret-token")

    def test_post_command_without_token_returns_403(self, client):
        resp = client.post("/api/commands/daily-report/run", json={"params": {}})
        assert resp.status_code == 403
        assert "X-Run-Token" in resp.json()["detail"]

    def test_post_command_with_wrong_token_returns_403(self, client):
        resp = client.post(
            "/api/commands/daily-report/run",
            json={"params": {}},
            headers={"X-Run-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_post_command_with_correct_token_allowed(self, client, mock_subprocess):
        resp = client.post(
            "/api/commands/daily-report/run",
            json={"params": {}},
            headers={"X-Run-Token": "test-secret-token"},
        )
        assert resp.status_code == 200
        assert "run_id" in resp.json()

    def test_get_report_without_token_returns_403(self, client, monkeypatch):
        import server.routes.reports as reports_mod
        from pathlib import Path
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = client.get("/api/reports/daily/2026-03-18")
        assert resp.status_code == 403

    def test_get_report_with_token_allowed(self, client, mock_subprocess, monkeypatch):
        import server.routes.reports as reports_mod
        from pathlib import Path
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = client.get(
            "/api/reports/daily/2026-03-18",
            headers={"X-Run-Token": "test-secret-token"},
        )
        # 202 = queued (file doesn't exist, run created)
        assert resp.status_code == 202

    def test_status_endpoint_no_token_required(self, client, monkeypatch):
        """Status endpoints are read-only — no token needed."""
        import server.routes.reports as reports_mod
        from pathlib import Path
        daily_dir = Path("/tmp/test-daily-status")
        daily_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
        resp = client.get("/api/reports/daily/2026-03-18/status")
        assert resp.status_code == 200

    def test_list_commands_no_token_required(self, client):
        """GET /api/commands is read-only — no token needed."""
        resp = client.get("/api/commands")
        assert resp.status_code == 200

    def test_list_runs_no_token_required(self, client):
        """GET /api/runs is read-only — no token needed."""
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_treasury_check_without_token_returns_403(self, client):
        resp = client.get("/api/reports/treasury/check/2026-03-18")
        assert resp.status_code == 403

    def test_ksb1_without_token_returns_403(self, client, monkeypatch):
        import server.routes.reports as reports_mod
        from pathlib import Path
        monkeypatch.setattr(reports_mod, "_KSB1_OUTPUT", Path("/nonexistent"))
        resp = client.get("/api/reports/ksb1/2026/3")
        assert resp.status_code == 403


class TestRunGuardDisabled:
    """Tests when RUN_TOKEN is empty — guard is disabled, all requests allowed."""

    @pytest.fixture(autouse=True)
    def _clear_token(self, monkeypatch):
        monkeypatch.setattr("server.config.settings.run_token", "")

    def test_post_command_allowed_without_token(self, client, mock_subprocess):
        resp = client.post("/api/commands/daily-report/run", json={"params": {}})
        assert resp.status_code == 200

    def test_get_report_allowed_without_token(self, client, mock_subprocess, monkeypatch):
        import server.routes.reports as reports_mod
        from pathlib import Path
        monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", Path("/nonexistent"))
        resp = client.get("/api/reports/daily/2026-03-18")
        assert resp.status_code == 202
