"""Report download endpoints.

GET /api/reports/daily/{date}
    Returns the daily store operation report Excel file for a given date.
    - If the file already exists on disk, serves it immediately.
    - If not, triggers a run to generate it and returns 202 Accepted with
      the run_id so the caller can poll /api/runs/{run_id} for completion.

GET /api/reports/daily/{date}/status
    Returns whether the report file for a date exists, and the latest
    pending/running run for that date (if any).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from server.config import settings
from server.routes.runs import RunStatus, _runs, create_run

router = APIRouter(prefix="/api/reports", tags=["reports"])

_DAILY_OUTPUT = settings.output_dir.resolve() / "daily-report"


def _report_path(report_date: date):
    return _DAILY_OUTPUT / f"database_report_{report_date.year}_{report_date.month:02d}_{report_date.day:02d}.xlsx"


def _active_run_for_date(report_date: date):
    """Return the most recent pending/running daily-report run for this date, or None."""
    date_str = report_date.isoformat()
    for run in reversed(list(_runs.values())):
        if run.command != "daily-report":
            continue
        if run.params.get("date") != date_str:
            continue
        if run.status in (RunStatus.PENDING, RunStatus.RUNNING):
            return run
    return None


@router.get("/daily/{report_date}")
async def get_daily_report(report_date: date):
    """Download the daily report for *report_date* (YYYY-MM-DD).

    - **200** — file returned directly.
    - **202** — file not ready; a generation run has been queued.
      Body: ``{"run_id": "...", "status": "pending", "message": "..."}``
    - **404** — run failed or date is clearly invalid.
    """
    path = _report_path(report_date)

    # Already on disk — serve it directly
    if path.is_file():
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # Check if there's already an active run for this date
    existing = _active_run_for_date(report_date)
    if existing:
        return _accepted(existing.id, existing.status.value, existing.queue_position)

    # Kick off a new run
    run = create_run("daily-report", {"date": report_date.isoformat()})
    return _accepted(run.id, run.status.value, run.queue_position)


@router.get("/daily/{report_date}/status")
async def get_daily_report_status(report_date: date):
    """Check whether the report for *report_date* is ready.

    Returns:
    - ``ready``: file exists on disk.
    - ``pending`` / ``running``: active run in progress.
    - ``not_found``: no file and no active run.
    """
    path = _report_path(report_date)

    if path.is_file():
        return {
            "date": report_date.isoformat(),
            "state": "ready",
            "file": path.name,
            "run_id": None,
            "queue_position": None,
        }

    active = _active_run_for_date(report_date)
    if active:
        return {
            "date": report_date.isoformat(),
            "state": active.status.value,
            "file": None,
            "run_id": active.id,
            "queue_position": active.queue_position,
        }

    return {
        "date": report_date.isoformat(),
        "state": "not_found",
        "file": None,
        "run_id": None,
        "queue_position": None,
    }


from fastapi.responses import JSONResponse


def _accepted(run_id: str, status: str, queue_position: int | None):
    return JSONResponse(
        status_code=202,
        content={
            "run_id": run_id,
            "status": status,
            "queue_position": queue_position,
            "message": "Report is being generated. Poll /api/runs/{run_id} for progress, "
                       "then re-request this endpoint when complete.",
        },
    )
