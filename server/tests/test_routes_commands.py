"""Tests for GET /api/commands and POST /api/commands/{name}/run."""


def test_list_commands(client):
    resp = client.get("/api/commands")
    assert resp.status_code == 200
    data = resp.json()
    names = {c["name"] for c in data}
    assert "daily-report" in names
    assert "ksb1" in names
    # Each entry has description
    for c in data:
        assert "description" in c


def test_run_command_success(client, mock_subprocess):
    resp = client.post("/api/commands/ksb1/run", json={"params": {"model": "qwen3:8b"}})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert body["status"] == "pending"


def test_run_command_no_body(client, mock_subprocess):
    resp = client.post("/api/commands/daily-report/run")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body


def test_run_command_not_found(client):
    resp = client.post("/api/commands/bogus/run")
    assert resp.status_code == 404
