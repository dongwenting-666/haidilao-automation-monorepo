
from __future__ import annotations
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse, RedirectResponse

from server.run_guard import require_run_token

from server.auth import LoginRequired
from server.routes import api_router
from server.routes.admin import router as admin_router
from server.routes.tools import router as tools_router, agent_router as tools_agent_router
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
    # Serve docs at non-default paths so scanners don't find them trivially.
    # Auth is enforced on the /openapi.json endpoint below.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url=None,  # served manually with auth below
)
app.include_router(api_router)
app.include_router(admin_router)
app.include_router(tools_router)
app.include_router(tools_agent_router)
app.include_router(github_webhook_router)


# ── Auth-gated API docs ───────────────────────────────────────────────────────
# openapi.json and the doc UIs require the same token as all other API endpoints.
# Scanners hitting /docs or /openapi.json get a 403, not the schema.

@app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(require_run_token)])
async def get_openapi():
    return JSONResponse(app.openapi())


@app.get("/api/docs", include_in_schema=False, dependencies=[Depends(require_run_token)])
async def get_docs():
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Haidilao API Docs")


@app.get("/api/redoc", include_in_schema=False, dependencies=[Depends(require_run_token)])
async def get_redoc():
    return get_redoc_html(openapi_url="/api/openapi.json", title="Haidilao API Docs")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    # For AJAX/API requests (POST, or requests expecting JSON), return 401 JSON
    # instead of a redirect so the client can handle it gracefully.
    accept = request.headers.get("accept", "")
    is_json_request = (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        or "application/json" in accept
        or request.headers.get("x-requested-with", "").lower() == "xmlhttprequest"
        or request.url.path.startswith("/api/")
        or "/upload" in request.url.path
        or "/files" in request.url.path
    )
    if is_json_request:
        return JSONResponse(
            {"ok": False, "error": "未登录，请先登录管理后台", "redirect": f"/admin/login?next={quote(exc.next_url)}"},
            status_code=401,
        )
    return RedirectResponse(url=f"/admin/login?next={quote(exc.next_url)}", status_code=302)
