"""Run guard — prevents unauthorized HTTP callers from triggering automation.

The scheduler's cron jobs call ``create_run()`` directly (in-process), so
they bypass this check entirely. Only HTTP callers (``POST /api/commands/*/run``,
``GET /api/reports/daily/*``, etc.) are gated.

When ``RUN_TOKEN`` is set in ``.env``, any HTTP request that would trigger
a new run must include::

    X-Run-Token: <token>

If the header is missing or wrong, the request is rejected with 403.
If ``RUN_TOKEN`` is empty (not configured), the guard is disabled and all
requests are allowed (backwards-compatible).

Usage in routes::

    from server.run_guard import require_run_token

    @router.post("/{name}/run", dependencies=[Depends(require_run_token)])
    async def run_command(name: str, ...): ...
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException

from server.config import settings

log = logging.getLogger(__name__)


async def require_run_token(x_run_token: str | None = Header(None)) -> None:
    """FastAPI dependency — reject requests without a valid run token.

    No-op if ``settings.run_token`` is empty (guard disabled).
    """
    if not settings.run_token:
        return  # guard disabled — all requests allowed

    if not x_run_token:
        log.warning("Run request blocked: missing X-Run-Token header")
        raise HTTPException(
            status_code=403,
            detail="X-Run-Token header required to trigger automation runs",
        )

    if x_run_token != settings.run_token:
        log.warning("Run request blocked: invalid X-Run-Token")
        raise HTTPException(
            status_code=403,
            detail="Invalid X-Run-Token",
        )
