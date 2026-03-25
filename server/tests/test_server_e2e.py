"""End-to-end test — start a real uvicorn server and exercise all API endpoints.

WARNING: This test triggers REAL automation commands (KSB1/SAP GUI).
Only run manually with: pytest -m e2e

PRODUCTION GUARD: This test is skipped unless HAIDILAO_E2E_ENABLED=1 is set.
This prevents it from running on production machines even if -m e2e is passed.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

_SERVER_DIR = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Start the server as a real subprocess and yield the base URL."""
    port = _free_port()
    env = {
        **os.environ,
        "SERVER_SERVER_HOST": "127.0.0.1",
        "SERVER_SERVER_PORT": str(port),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        env=env,
        cwd=_SERVER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"

    # Wait for server to be ready (up to 10 s)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{base}/api/commands", timeout=1)
            break
        except httpx.ConnectError:
            time.sleep(0.3)
    else:
        proc.kill()
        out = proc.stdout.read().decode() if proc.stdout else ""
        pytest.fail(f"Server failed to start within 10 s. Output:\n{out}")

    yield base

    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("HAIDILAO_E2E_ENABLED") != "1",
    reason="E2E tests disabled on this machine. Set HAIDILAO_E2E_ENABLED=1 to run."
)
def test_full_lifecycle(server):
    """Exercise every API endpoint in a single lifecycle test."""
    base = server

    with httpx.Client(base_url=base, timeout=30) as c:
        # 1. List commands
        resp = c.get("/api/commands")
        assert resp.status_code == 200
        commands = resp.json()
        names = {cmd["name"] for cmd in commands}
        assert "ksb1" in names
        assert "daily-report" in names

        # 2. List jobs
        resp = c.get("/api/jobs")
        assert resp.status_code == 200
        jobs = resp.json()
        assert any(j["id"] == "daily-report-cron" for j in jobs)

        # 3. List runs (initially empty)
        resp = c.get("/api/runs")
        assert resp.status_code == 200

        # 4. Trigger a command — it may fail (no SAP/QBI env) but
        #    the run object must be created and eventually finish.
        resp = c.post("/api/commands/ksb1/run", json={"params": {}})
        assert resp.status_code == 200
        body = resp.json()
        run_id = body["run_id"]
        assert body["status"] == "pending"

        # 5. Poll briefly — the run should at least transition out of
        #    pending (to running/failed). Allow up to 60 s for `uv run`
        #    to resolve deps and fail.
        final_data = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            resp = c.get(f"/api/runs/{run_id}")
            assert resp.status_code == 200
            data = resp.json()
            if data["status"] in ("success", "failed"):
                final_data = data
                break
            time.sleep(1)

        # If the run finished, verify logs field is present
        if final_data is not None:
            assert "logs" in final_data
        # If still running after 60 s (e.g. waiting on SAP), that's OK
        # — we already verified the run was created and the API returned it

        # 6. List runs again — should contain our run
        resp = c.get("/api/runs")
        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()}
        assert run_id in ids

        # 7. Files listing (may be empty or populated depending on output dir)
        resp = c.get("/api/files/")
        # 200 if output dir exists, 404 if not — both acceptable
        assert resp.status_code in (200, 404)

        # 8. 404 for unknown command
        resp = c.post("/api/commands/nonexistent/run")
        assert resp.status_code == 404

        # 9. 404 for unknown run
        resp = c.get("/api/runs/doesnotexist")
        assert resp.status_code == 404
