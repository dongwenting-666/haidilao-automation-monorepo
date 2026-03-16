"""Tests for server.routes.runs — Run model, eviction, execute_run, endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from server.routes.runs import (
    _MAX_HISTORY,
    Run,
    RunStatus,
    _evict_old_runs,
    _runs,
    execute_run,
)


# --- RunStatus enum ---


def test_run_status_values():
    assert RunStatus.PENDING.value == "pending"
    assert RunStatus.RUNNING.value == "running"
    assert RunStatus.SUCCESS.value == "success"
    assert RunStatus.FAILED.value == "failed"


# --- Run model ---


class TestRun:
    def test_init_defaults(self):
        r = Run("ksb1", {"model": "x"})
        assert len(r.id) == 12
        assert r.command == "ksb1"
        assert r.params == {"model": "x"}
        assert r.status == RunStatus.PENDING
        assert isinstance(r.started_at, datetime)
        assert r.finished_at is None
        assert r.logs == ""

    def test_to_dict_without_logs(self):
        r = Run("ksb1", {})
        r.logs = "some output"
        d = r.to_dict(include_logs=False)
        assert "logs" not in d
        assert d["command"] == "ksb1"
        assert d["status"] == "pending"
        assert d["finished_at"] is None

    def test_to_dict_with_logs(self):
        r = Run("ksb1", {})
        r.logs = "hello"
        r.finished_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        d = r.to_dict(include_logs=True)
        assert d["logs"] == "hello"
        assert d["finished_at"] is not None


# --- _evict_old_runs ---


class TestEviction:
    def test_under_limit_noop(self):
        _runs.clear()
        for i in range(5):
            r = Run("cmd", {})
            r.status = RunStatus.SUCCESS
            _runs[r.id] = r
        _evict_old_runs()
        assert len(_runs) == 5

    def test_over_limit_evicts_completed(self):
        _runs.clear()
        for i in range(_MAX_HISTORY + 5):
            r = Run("cmd", {})
            r.status = RunStatus.SUCCESS
            _runs[r.id] = r
        _evict_old_runs()
        assert len(_runs) <= _MAX_HISTORY

    def test_skips_running(self):
        _runs.clear()
        # First run is RUNNING — should be kept
        running = Run("cmd", {})
        running.status = RunStatus.RUNNING
        _runs[running.id] = running
        for i in range(_MAX_HISTORY + 5):
            r = Run("cmd", {})
            r.status = RunStatus.SUCCESS
            _runs[r.id] = r
        _evict_old_runs()
        assert running.id in _runs


# --- execute_run ---


@pytest.mark.asyncio
async def test_execute_run_success():
    r = Run("ksb1", {})
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"done\n", None)
    mock_proc.returncode = 0

    with patch("server.routes.runs.asyncio.create_subprocess_exec", return_value=mock_proc):
        await execute_run(r)

    assert r.status == RunStatus.SUCCESS
    assert r.logs == "done\n"
    assert r.finished_at is not None


@pytest.mark.asyncio
async def test_execute_run_failure():
    r = Run("ksb1", {"model": "test"})
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"error\n", None)
    mock_proc.returncode = 1

    with patch("server.routes.runs.asyncio.create_subprocess_exec", return_value=mock_proc):
        await execute_run(r)

    assert r.status == RunStatus.FAILED
    assert "error" in r.logs


@pytest.mark.asyncio
async def test_execute_run_unknown_command():
    r = Run("nonexistent", {})
    await execute_run(r)
    assert r.status == RunStatus.FAILED
    assert "Unknown command" in r.logs


# --- Endpoints via TestClient ---


def test_list_runs_empty(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_get_run(client, mock_subprocess):
    # Trigger a run via the commands endpoint
    resp = client.post("/api/commands/ksb1/run")
    run_id = resp.json()["run_id"]

    # List should contain it
    runs = client.get("/api/runs").json()
    assert any(r["id"] == run_id for r in runs)

    # Get by ID should include logs
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["id"] == run_id
    assert "logs" in detail


def test_get_run_not_found(client):
    resp = client.get("/api/runs/doesnotexist")
    assert resp.status_code == 404
