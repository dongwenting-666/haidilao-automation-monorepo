from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.routes import api_router
from server.scheduler import scheduler, setup_default_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_default_jobs()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Haidilao Automation Server",
    description="HTTP API for triggering automation commands, viewing run history, and downloading output files.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)
