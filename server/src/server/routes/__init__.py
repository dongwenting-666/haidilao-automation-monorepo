from fastapi import APIRouter

from server.routes.commands import router as commands_router
from server.routes.files import router as files_router
from server.routes.jobs import router as jobs_router
from server.routes.reports import router as reports_router
from server.routes.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(commands_router)
api_router.include_router(files_router)
api_router.include_router(jobs_router)
api_router.include_router(reports_router)
api_router.include_router(runs_router)
