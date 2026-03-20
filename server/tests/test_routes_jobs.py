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
    # Find the daily-report job by ID (don't assume ordering)
    daily_jobs = [j for j in data if j["id"] == "daily-report-cron"]
    assert len(daily_jobs) == 1, f"Expected daily-report-cron in jobs, got: {[j['id'] for j in data]}"
    job = daily_jobs[0]
    assert job["name"] == "Daily store operation report"
    assert "trigger" in job

    # Clean up
    scheduler.remove_all_jobs()
