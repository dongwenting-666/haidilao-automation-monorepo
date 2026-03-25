"""Shared fixtures for server tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_runs():
    """Clear the global _runs dict before each test."""
    from server.routes.runs import _runs

    _runs.clear()
    yield
    _runs.clear()


TEST_RUN_TOKEN = "test-token"

@pytest.fixture(autouse=True)
def _disable_run_guard(monkeypatch):
    """Set a predictable test RUN_TOKEN and enable SAP for tests.

    All tests use X-Run-Token: test-token for authenticated requests.
    Tests in test_run_guard.py override run_token as needed.
    """
    monkeypatch.setenv("HAIDILAO_SAP_ENABLED", "1")  # allow ksb1 runs in tests
    monkeypatch.setattr("server.config.settings.run_token", TEST_RUN_TOKEN)
    import server.api_keys as _ak
    monkeypatch.setattr(_ak, "verify_api_key", lambda key: None)  # no API keys in tests


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Auth headers for tests that hit protected endpoints."""
    return {"X-Run-Token": TEST_RUN_TOKEN}


@pytest.fixture()
def tmp_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point _OUTPUT_ROOT at a temp directory and populate it with sample files."""
    import server.routes.files as files_mod

    monkeypatch.setattr(files_mod, "_OUTPUT_ROOT", tmp_path)

    # Create sample structure: subdir/hello.txt
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "report.xlsx").write_text("fake-excel")
    (sub / "hello.txt").write_text("hello world")
    return tmp_path


@pytest.fixture()
def mock_subprocess():
    """Mock asyncio.create_subprocess_exec to avoid spawning real processes."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"ok\n", None)
    mock_proc.returncode = 0

    with patch("server.routes.runs.asyncio.create_subprocess_exec", return_value=mock_proc) as m:
        yield m


@pytest.fixture()
def client():
    """FastAPI TestClient with the test RUN_TOKEN pre-set in headers."""
    from server.app import app

    with TestClient(
        app,
        raise_server_exceptions=False,
        headers={"X-Run-Token": TEST_RUN_TOKEN},
    ) as c:
        yield c


@pytest.fixture()
def unauthed_client():
    """FastAPI TestClient with NO auth headers — for testing 403 responses."""
    from server.app import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
