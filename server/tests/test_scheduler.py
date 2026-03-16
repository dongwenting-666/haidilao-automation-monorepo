"""Tests for server.scheduler."""

import pytest


def test_parse_cron_valid():
    from server.scheduler import _parse_cron

    result = _parse_cron("30 6 * * 1-5")
    assert result == {
        "minute": "30",
        "hour": "6",
        "day": "*",
        "month": "*",
        "day_of_week": "1-5",
    }


def test_parse_cron_invalid_too_few():
    from server.scheduler import _parse_cron

    with pytest.raises(ValueError, match="Expected 5-field"):
        _parse_cron("30 6 *")


def test_parse_cron_invalid_too_many():
    from server.scheduler import _parse_cron

    with pytest.raises(ValueError, match="Expected 5-field"):
        _parse_cron("30 6 * * 1-5 2026")


def test_setup_default_jobs():
    from server.scheduler import scheduler, setup_default_jobs

    # Remove any existing jobs from prior tests
    scheduler.remove_all_jobs()
    setup_default_jobs()

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "daily-report-cron"
    assert job.name == "Daily store operation report"
    # Clean up
    scheduler.remove_all_jobs()


@pytest.mark.asyncio
async def test_run_daily_report_creates_run():
    from server.routes.runs import _runs
    from server.scheduler import _run_daily_report

    _runs.clear()
    await _run_daily_report()
    assert len(_runs) == 1
    run = next(iter(_runs.values()))
    assert run.command == "daily-report"
