
from __future__ import annotations
from fastapi import APIRouter

from server.routes.files import router as files_router
from server.routes.jobs import router as jobs_router
from server.routes.reports import router as reports_router
from server.routes.runs import router as runs_router

api_router = APIRouter()
# NOTE: commands_router intentionally removed — generic "run any command" endpoint
# was an attack surface. All automation is triggered via specific /api/reports/ endpoints
# or directly by the APScheduler cron jobs (in-process, no HTTP involved).
api_router.include_router(files_router)
api_router.include_router(jobs_router)
api_router.include_router(reports_router)
api_router.include_router(runs_router)
