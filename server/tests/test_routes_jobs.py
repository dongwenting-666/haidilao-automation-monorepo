"""Tests for GET /api/jobs."""

from server.scheduler import scheduler, setup_default_jobs


def test_list_jobs(client):
    # Ensure a clean slate regardless of lifespan state
    scheduler.remove_all_jobs()
    setup_default_jobs()

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    job = data[0]
    assert job["id"] == "daily-report-cron"
    assert job["name"] == "Daily store operation report"
    assert "trigger" in job

    # Clean up
    scheduler.remove_all_jobs()
