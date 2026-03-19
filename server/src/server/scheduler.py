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
    create_run("daily-report", {})


async def _run_treasury_loan_watch() -> None:
    """Trigger treasury-loan-watch command via the run system."""
    from server.routes.runs import create_run
    create_run("treasury-loan-watch", {})


def setup_default_jobs() -> None:
    """Register the default cron jobs."""
    # Daily store operation report
    trigger = CronTrigger(**_parse_cron(settings.daily_report_cron))
    scheduler.add_job(
        _run_daily_report,
        trigger=trigger,
        id="daily-report-cron",
        name="Daily store operation report",
        replace_existing=True,
    )

    # Treasury loan maturity watch — 6 AM Vancouver time (America/Vancouver = UTC-7/8)
    scheduler.add_job(
        _run_treasury_loan_watch,
        CronTrigger(hour=6, minute=0, timezone="America/Vancouver"),
        id="treasury-loan-watch-cron",
        name="Treasury loan maturity watch",
        replace_existing=True,
    )
