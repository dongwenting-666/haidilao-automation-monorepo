"""Tests for /api/reports/daily and /api/reports/ksb1 endpoints."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest


REPORT_DATE = date(2026, 2, 10)
DATE_STR = "2026-02-10"
DAILY_FILENAME = "database_report_2026_02_10.xlsx"

KSB1_YEAR = 2026
KSB1_MONTH = 2
KSB1_YEAR_MONTH = "2026-02"
KSB1_FILENAME = "2026-02_KSB1_检查报告_120000.XLSX"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def daily_report_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import server.routes.reports as reports_mod
    daily_dir = tmp_path / "daily-report"
    daily_dir.mkdir()
    report = daily_dir / DAILY_FILENAME
    report.write_bytes(b"fake-excel-content")
    monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
    return report


@pytest.fixture()
def no_daily_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import server.routes.reports as reports_mod
    daily_dir = tmp_path / "daily-report"
    daily_dir.mkdir()
    monkeypatch.setattr(reports_mod, "_DAILY_OUTPUT", daily_dir)
    return daily_dir


@pytest.fixture()
def ksb1_report_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import server.routes.reports as reports_mod
    ksb1_dir = tmp_path / "ksb1" / KSB1_YEAR_MONTH
    ksb1_dir.mkdir(parents=True)
    report = ksb1_dir / KSB1_FILENAME
    report.write_bytes(b"fake-ksb1-excel")
    monkeypatch.setattr(reports_mod, "_KSB1_OUTPUT", tmp_path / "ksb1")
    return report


@pytest.fixture()
def no_ksb1_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import server.routes.reports as reports_mod
    ksb1_dir = tmp_path / "ksb1"
    ksb1_dir.mkdir()
    monkeypatch.setattr(reports_mod, "_KSB1_OUTPUT", ksb1_dir)
    return ksb1_dir


# ---------------------------------------------------------------------------
# Daily report — download
# ---------------------------------------------------------------------------

def test_daily_report_file_exists(client, daily_report_file):
    resp = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp.status_code == 200
    assert resp.content == b"fake-excel-content"


def test_daily_report_triggers_run(client, no_daily_report, mock_subprocess):
    resp = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["status"] in ("pending", "running", "success")


def test_daily_report_deduplicates_run(client, no_daily_report, mock_subprocess):
    resp1 = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp1.status_code == 202
    run_id_1 = resp1.json()["run_id"]

    from server.routes.runs import _runs, RunStatus
    _runs[run_id_1].status = RunStatus.PENDING

    resp2 = client.get(f"/api/reports/daily/{DATE_STR}")
    assert resp2.status_code == 202
    assert resp2.json()["run_id"] == run_id_1


def test_daily_report_invalid_date(client):
    resp = client.get("/api/reports/daily/not-a-date")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Daily report — status
# ---------------------------------------------------------------------------

def test_daily_status_ready(client, daily_report_file):
    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready"
    assert resp.json()["file"] == DAILY_FILENAME


def test_daily_status_not_found(client, no_daily_report):
    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    assert resp.json()["state"] == "not_found"


def test_daily_status_pending(client, no_daily_report, mock_subprocess):
    client.get(f"/api/reports/daily/{DATE_STR}")

    from server.routes.runs import _runs, RunStatus
    for run in _runs.values():
        if run.command == "daily-report":
            run.status = RunStatus.PENDING
            break

    resp = client.get(f"/api/reports/daily/{DATE_STR}/status")
    assert resp.json()["state"] == "pending"


# ---------------------------------------------------------------------------
# KSB1 report — download
# ---------------------------------------------------------------------------

def test_ksb1_report_file_exists(client, ksb1_report_file):
    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")
    assert resp.status_code == 200
    assert resp.content == b"fake-ksb1-excel"


def test_ksb1_report_triggers_run(client, no_ksb1_report, mock_subprocess):
    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body


def test_ksb1_report_deduplicates_run(client, no_ksb1_report, mock_subprocess):
    resp1 = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")
    run_id = resp1.json()["run_id"]

    from server.routes.runs import _runs, RunStatus
    _runs[run_id].status = RunStatus.PENDING

    resp2 = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")
    assert resp2.json()["run_id"] == run_id


def test_ksb1_report_invalid_month(client, no_ksb1_report):
    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/13")
    assert resp.status_code == 422


def test_ksb1_report_picks_latest_file(client, tmp_path, monkeypatch):
    """When multiple report files exist, serve the most recent one."""
    import server.routes.reports as reports_mod
    ksb1_dir = tmp_path / "ksb1" / KSB1_YEAR_MONTH
    ksb1_dir.mkdir(parents=True)
    old = ksb1_dir / f"{KSB1_YEAR_MONTH}_KSB1_检查报告_090000.XLSX"
    new = ksb1_dir / f"{KSB1_YEAR_MONTH}_KSB1_检查报告_180000.XLSX"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    monkeypatch.setattr(reports_mod, "_KSB1_OUTPUT", tmp_path / "ksb1")

    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")
    assert resp.status_code == 200
    assert resp.content == b"new"


# ---------------------------------------------------------------------------
# KSB1 report — status
# ---------------------------------------------------------------------------

def test_ksb1_status_ready(client, ksb1_report_file):
    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}/status")
    assert resp.json()["state"] == "ready"
    assert KSB1_YEAR_MONTH in resp.json()["file"]


def test_ksb1_status_not_found(client, no_ksb1_report):
    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}/status")
    assert resp.json()["state"] == "not_found"


def test_ksb1_status_pending(client, no_ksb1_report, mock_subprocess):
    client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}")

    from server.routes.runs import _runs, RunStatus
    for run in _runs.values():
        if run.command == "ksb1":
            run.status = RunStatus.PENDING
            break

    resp = client.get(f"/api/reports/ksb1/{KSB1_YEAR}/{KSB1_MONTH}/status")
    assert resp.json()["state"] == "pending"
    assert resp.json()["year"] == KSB1_YEAR
    assert resp.json()["month"] == KSB1_MONTH
