from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.routes import api_router
from server.routes.admin import router as admin_router
from server.routes.runs import start_queue_worker
from server.scheduler import scheduler, setup_default_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_default_jobs()
    scheduler.start()
    start_queue_worker()

    from server.db import maybe_run_migrations
    maybe_run_migrations()  # no-op if DATABASE_URL not set

    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Haidilao Automation Server",
    description="HTTP API for triggering automation commands, viewing run history, and downloading output files.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)
app.include_router(admin_router)
