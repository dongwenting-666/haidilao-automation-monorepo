from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from server.auth import LoginRequired
from server.routes import api_router
from server.routes.admin import router as admin_router
from server.routes.tools import router as tools_router
from server.routes.github_webhook import router as github_webhook_router
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
app.include_router(tools_router)
app.include_router(github_webhook_router)


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url=f"/admin/login?next={quote(exc.next_url)}", status_code=302)
