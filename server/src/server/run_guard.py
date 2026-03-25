"""Run guard — prevents unauthorized HTTP callers from triggering automation.

Uses the per-user API key system (``server.api_keys``) with the
``runs:trigger`` scope. Falls back to ``RUN_TOKEN`` header if no API keys
exist yet (backwards compatible).

The scheduler's cron jobs call ``create_run()`` directly (in-process), so
they bypass this check entirely.

Auth is ALWAYS required. There is no "allow all if unconfigured" fallback —
that was the root cause of unauthorized SAP automation being triggered.

Usage in routes::

    from server.run_guard import require_run_token

    @router.post("/{name}/run", dependencies=[Depends(require_run_token)])
    async def run_command(name: str, ...): ...
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException, Request

from server.config import settings

log = logging.getLogger(__name__)


async def require_run_token(
    request: Request,
    x_api_key: str | None = Header(None),
    x_run_token: str | None = Header(None),
) -> None:
    """FastAPI dependency — require runs:trigger scope or valid RUN_TOKEN.

    Checks in order:
    1. X-API-Key header → verify via api_keys module, require ``runs:trigger`` scope
    2. X-Run-Token header → check against ``settings.run_token``
    3. No valid auth → always 403. No unauthenticated fallback.

    The scheduler calls ``create_run()`` directly and bypasses this entirely.
    """
    from server.api_keys import verify_api_key

    # 1. Try API key first
    raw_key = x_api_key or request.query_params.get("api_key")
    if raw_key:
        record = verify_api_key(raw_key)
        if record is None:
            raise HTTPException(status_code=403, detail="Invalid or revoked API key")
        user_scopes = {s.strip() for s in record.get("scopes", "").split(",") if s.strip()}
        if "admin" not in user_scopes and "runs:trigger" not in user_scopes:
            raise HTTPException(status_code=403, detail="API key missing runs:trigger scope")
        return  # authorized

    # 2. Try RUN_TOKEN (legacy)
    if settings.run_token and x_run_token == settings.run_token:
        return  # authorized

    # 3. Deny — auth is always required
    log.warning(
        "Blocked unauthenticated request: %s %s from %s",
        request.method, request.url.path, request.client.host if request.client else "unknown",
    )
    raise HTTPException(
        status_code=403,
        detail="Authentication required: provide X-API-Key or X-Run-Token header",
    )
