"""Report download endpoints.

Daily store operation report:
  GET /api/reports/daily/{date}           — download or trigger generation
  GET /api/reports/daily/{date}/status    — check status

KSB1 accounting check report:
  GET /api/reports/ksb1/{year}/{month}        — download or trigger generation
  GET /api/reports/ksb1/{year}/{month}/status — check status

For both endpoints:
  - 200: file returned directly (already on disk)
  - 202: queued; body has run_id to poll via /api/runs/{run_id}
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from server.config import settings
from server.routes.runs import RunStatus, _runs, create_run

router = APIRouter(prefix="/api/reports", tags=["reports"])

_DAILY_OUTPUT = settings.output_dir.resolve() / "daily-report"
_KSB1_OUTPUT = settings.output_dir.resolve() / "ksb1"

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_run(command: str, match_params: dict) -> object | None:
    """Return the most recent pending/running run matching command + params."""
    for run in reversed(list(_runs.values())):
        if run.command != command:
            continue
        if any(run.params.get(k) != v for k, v in match_params.items()):
            continue
        if run.status in (RunStatus.PENDING, RunStatus.RUNNING):
            return run
    return None


def _accepted(run_id: str, status: str, queue_position: int | None) -> JSONResponse:
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


def _serve_or_queue(path: Path | None, command: str, params: dict) -> object:
    """Serve *path* directly (200) or queue a run and return 202."""
    if path is not None and path.is_file():
        return FileResponse(path, filename=path.name, media_type=_EXCEL_MIME)

    existing = _active_run(command, params)
    if existing:
        return _accepted(existing.id, existing.status.value, existing.queue_position)

    run = create_run(command, params)
    return _accepted(run.id, run.status.value, run.queue_position)


def _status_body(identifier: dict, path: Path | None, command: str, params: dict) -> dict:
    if path is not None and path.is_file():
        return {**identifier, "state": "ready", "file": path.name, "run_id": None, "queue_position": None}

    active = _active_run(command, params)
    if active:
        return {**identifier, "state": active.status.value, "file": None,
                "run_id": active.id, "queue_position": active.queue_position}

    return {**identifier, "state": "not_found", "file": None, "run_id": None, "queue_position": None}


# ---------------------------------------------------------------------------
# Daily store operation report
# ---------------------------------------------------------------------------

def _daily_report_path(report_date: date) -> Path:
    return _DAILY_OUTPUT / f"database_report_{report_date.year}_{report_date.month:02d}_{report_date.day:02d}.xlsx"


@router.get("/daily/{report_date}")
async def get_daily_report(report_date: date, no_cache: bool = False):
    """Download the daily store operation report for *report_date* (YYYY-MM-DD).

    Pass ``?no_cache=true`` to force regeneration even if a file already exists.
    """
    path = _daily_report_path(report_date)
    if no_cache and path.is_file():
        path.unlink()
    return _serve_or_queue(
        path,
        "daily-report",
        {"date": report_date.isoformat()},
    )


@router.get("/daily/{report_date}/status")
async def get_daily_report_status(report_date: date):
    """Check whether the daily report for *report_date* is ready."""
    return _status_body(
        {"date": report_date.isoformat()},
        _daily_report_path(report_date),
        "daily-report",
        {"date": report_date.isoformat()},
    )


# ---------------------------------------------------------------------------
# KSB1 accounting check report
# ---------------------------------------------------------------------------

def _ksb1_report_path(year: int, month: int) -> Path | None:
    """Find the latest KSB1 report file for the given year/month, or None."""
    year_month = f"{year}-{month:02d}"
    output_dir = _KSB1_OUTPUT / year_month
    if not output_dir.is_dir():
        return None
    # Filename pattern: {YYYY-MM}_KSB1_检查报告_{HHMMSS}.XLSX
    candidates = sorted(output_dir.glob(f"{year_month}_KSB1_*.XLSX"))
    return candidates[-1] if candidates else None


@router.get("/ksb1/{year}/{month}")
async def get_ksb1_report(year: int, month: int):
    """Download the KSB1 accounting check report for *year*/*month*.

    Generates the report if it doesn't exist yet (downloads from SAP).
    """
    if not (1 <= month <= 12):
        return JSONResponse(status_code=422, content={"detail": "month must be 1-12"})

    return _serve_or_queue(
        _ksb1_report_path(year, month),
        "ksb1",
        {"month": month, "year": year},
    )


@router.get("/ksb1/{year}/{month}/status")
async def get_ksb1_report_status(year: int, month: int):
    """Check whether the KSB1 report for *year*/*month* is ready."""
    if not (1 <= month <= 12):
        return JSONResponse(status_code=422, content={"detail": "month must be 1-12"})

    path = _ksb1_report_path(year, month)
    return _status_body(
        {"year": year, "month": month},
        path,
        "ksb1",
        {"month": month, "year": year},
    )
