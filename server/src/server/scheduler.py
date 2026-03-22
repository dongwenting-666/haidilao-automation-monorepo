
from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from server.config import settings

scheduler = AsyncIOScheduler()


def _parse_cron(expr: str) -> dict[str, str]:
    """Parse a 5-field cron expression into CronTrigger kwargs."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {expr!r}")
    return dict(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )


async def _run_daily_report() -> None:
    """Trigger daily-report command via the run system."""
    from server.routes.runs import create_run
    create_run("daily-report", {}, notify_chat="production_accounting_report_chat")


async def _run_treasury_loan_watch() -> None:
    """Trigger treasury-loan-watch command via the run system."""
    from server.routes.runs import create_run
    create_run("treasury-loan-watch", {}, notify_chat="hongming")


async def _run_store_hours_collect() -> None:
    """Trigger store-hours-collect command via the run system."""
    from server.routes.runs import create_run
    # Run-complete card (data-fill summary) goes to admin (hongming).
    # The store_hours group receives the unfilled-store alert sent directly by store_hours_collect.main.
    create_run("store-hours-collect", {}, notify_chat="hongming")


def setup_default_jobs() -> None:
    """Register the default cron jobs."""
    # Daily store operation report — default: 6:00 AM Vancouver time.
    # The cron expression in settings is interpreted as Vancouver time so that
    # the T-2 data reliability constraint is evaluated against the same clock
    # that main.py uses (ZoneInfo("America/Vancouver")).
    trigger = CronTrigger(**_parse_cron(settings.daily_report_cron), timezone="America/Vancouver")
    scheduler.add_job(
        _run_daily_report,
        trigger=trigger,
        id="daily-report-cron",
        name="Daily store operation report",
        replace_existing=True,
    )

    # Treasury loan maturity watch — 6:00 AM Vancouver time
    scheduler.add_job(
        _run_treasury_loan_watch,
        CronTrigger(hour=6, minute=0, timezone="America/Vancouver"),
        id="treasury-loan-watch-cron",
        name="Treasury loan maturity watch",
        replace_existing=True,
    )

    # Store working-hour data collection — 6:30 AM Vancouver time
    scheduler.add_job(
        _run_store_hours_collect,
        CronTrigger(hour=6, minute=30, timezone="America/Vancouver"),
        id="store-hours-collect-cron",
        name="Store working-hour data collection",
        replace_existing=True,
    )
