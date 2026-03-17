"""Tests for /api/reports/daily endpoints."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


REPORT_DATE = date(2026, 2, 10)
DATE_STR = "2026-02-10"
FILENAME = "database_report_2026_02_10.xlsx"


@pytest.fixture()
def report_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a fake report file and point the router at tmp_path."""
    import server.routes.reports as reports_mod

    daily_dir = tmp_path / "daily-report"
    daily_dir.mkdir()
    report = daily_dir / FILENAME
    report.write_bytes(b"fake-excel-content")

    monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
    return report


@pytest.fixture()
def no_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the router at an empty directory (no report file)."""
    import server.routes.reports as reports_mod

    daily_dir = tmp_path / "daily-report"
    daily_dir.mkdir()
    monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
    return daily_dir


# --- GET /api/reports/daily/{date} ---


def test_get_daily_report_file_exists(client, report_file):
    resp = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert resp.content == b"fake-excel-content"


def test_get_daily_report_triggers_run(client, no_report, mock_subprocess):
    resp = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["status"] in ("pending", "running", "success")


def test_get_daily_report_deduplicates_run(client, no_report, mock_subprocess):
    """Two requests for the same date should reuse the existing run."""
    resp1 = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp1.status_code == 202
    run_id_1 = resp1.json()["run_id"]

    # Manually set back to pending so _active_run_for_date finds it
    from server.routes.runs import _runs, RunStatus
    _runs[run_id_1].status = RunStatus.PENDING

    resp2 = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp2.status_code == 202
    assert resp2.json()["run_id"] == run_id_1


def test_get_daily_report_invalid_date(client):
    resp = client.get("/api/reports/daily/not-a-date")
    assert resp.status_code == 422


# --- GET /api/reports/daily/{date}/status ---


def test_status_ready(client, report_file):
    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["file"] == FILENAME
    assert body["run_id"] is None


def test_status_not_found(client, no_report):
    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "not_found"
    assert body["file"] is None


def test_status_pending(client, no_report, mock_subprocess):
    # Trigger a run first
    client.get(f"/api/reports/daily/{DATE_STR}")

    # Force status to pending
    from server.routes.runs import _runs, RunStatus
    for run in _runs.values():
        if run.command == "daily-report":
            run.status = RunStatus.PENDING
            break

    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    body = resp.json()
    assert body["state"] == "pending"
    assert body["run_id"] is not None
