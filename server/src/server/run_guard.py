"""Run guard — prevents unauthorized HTTP callers from triggering automation.

Uses the per-user API key system (``server.api_keys``) with the
``runs:trigger`` scope. Falls back to ``RUN_TOKEN`` header if no API keys
exist yet (backwards compatible).

The scheduler's cron jobs call ``create_run()`` directly (in-process), so
they bypass this check entirely.

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
    2. X-Run-Token header → check against ``settings.run_token`` (legacy fallback)
    3. If neither auth mechanism is configured (no API keys, no RUN_TOKEN) → allow all

    The scheduler calls ``create_run()`` directly and bypasses this entirely.
    """
    from server.api_keys import has_any_api_keys, verify_api_key

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
    if settings.run_token:
        if x_run_token == settings.run_token:
            return  # authorized
        if x_run_token:
            raise HTTPException(status_code=403, detail="Invalid X-Run-Token")
        # No X-Run-Token header — fall through to check if we should require it

    # 3. If any API keys exist in DB, require one
    if has_any_api_keys():
        raise HTTPException(status_code=403, detail="X-API-Key header required")

    # 4. If RUN_TOKEN is set but not provided
    if settings.run_token:
        log.warning("Run request blocked: missing X-Run-Token or X-API-Key header")
        raise HTTPException(status_code=403, detail="X-API-Key or X-Run-Token header required")

    # 5. No auth configured at all — allow (backwards compatible)
    return
