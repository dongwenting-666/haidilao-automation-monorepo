"""Per-user API key authentication for server endpoints.

Keys are generated via the admin UI (super-admin only) and stored as
SHA-256 hashes in the ``api_keys`` DB table. The raw key is shown once
at creation time and never stored.

Key format: ``hld_<32 hex chars>`` (e.g. ``hld_a1b2c3d4...``)

Usage in routes::

    from server.api_keys import require_api_key, require_scope

    # Any valid API key
    @router.get("/data", dependencies=[Depends(require_api_key)])

    # Specific scope required
    @router.post("/run", dependencies=[Depends(require_scope("runs:trigger"))])

Available scopes:
    - ``runs:trigger`` — trigger automation runs (POST /api/commands/*/run, etc.)
    - ``reports:read`` — download report files
    - ``files:read`` — list/download output files
    - ``admin`` — full admin access (super-admin operations)

Backwards compatibility:
    When no API keys exist in the DB, the system falls back to ``RUN_TOKEN``
    header check (if configured). Once any API key is created, ``RUN_TOKEN``
    is ignored and only API keys are accepted.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import Header, HTTPException, Request

log = logging.getLogger(__name__)

_KEY_PREFIX = "hld_"


def generate_key() -> str:
    """Generate a new raw API key: ``hld_<32 hex chars>``."""
    return f"{_KEY_PREFIX}{secrets.token_hex(16)}"


def hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def key_prefix(raw_key: str) -> str:
    """First 12 chars of the raw key for display (e.g. ``hld_a1b2c3d4``)."""
    return raw_key[:12]


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def create_api_key(open_id: str, label: str, scopes: str) -> tuple[str, dict]:
    """Create a new API key for a user.

    Returns ``(raw_key, key_record)`` — the raw key is shown once and never stored.
    """
    from server.db import get_db
    db = get_db()
    if db is None:
        raise RuntimeError("DB not available")

    raw = generate_key()
    h = hash_key(raw)
    prefix = key_prefix(raw)

    db.execute(
        """
        INSERT INTO api_keys (key_hash, key_prefix, open_id, label, scopes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (h, prefix, open_id, label, scopes),
    )
    log.info("API key created for %s (prefix=%s, scopes=%s)", open_id, prefix, scopes)
    return raw, {"key_prefix": prefix, "open_id": open_id, "label": label, "scopes": scopes}


def verify_api_key(raw_key: str) -> dict | None:
    """Look up an API key by its raw value.

    Returns the key record (with scopes) if valid, None if not found or revoked.
    Also updates ``last_used_at``.
    """
    from server.db import get_db
    db = get_db()
    if db is None:
        return None

    h = hash_key(raw_key)
    row = db.fetchone(
        """
        SELECT open_id, label, scopes, created_at, revoked_at
        FROM api_keys
        WHERE key_hash = %s AND revoked_at IS NULL
        """,
        (h,),
    )
    if row is None:
        return None

    # Update last_used_at (best-effort)
    try:
        db.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = %s",
            (h,),
        )
    except Exception:
        pass

    return {
        "open_id": row["open_id"],
        "label": row["label"],
        "scopes": row["scopes"],
    }


def revoke_api_key(key_id: int) -> bool:
    """Revoke an API key by its DB id. Returns True if found and revoked."""
    from server.db import get_db
    db = get_db()
    if db is None:
        return False

    db.execute(
        "UPDATE api_keys SET revoked_at = NOW() WHERE id = %s AND revoked_at IS NULL",
        (key_id,),
    )
    return True


def list_api_keys(open_id: str | None = None) -> list[dict]:
    """List API keys, optionally filtered by user. Never returns the hash."""
    from server.db import get_db
    db = get_db()
    if db is None:
        return []

    if open_id:
        rows = db.fetchall(
            """
            SELECT id, key_prefix, open_id, label, scopes, created_at, last_used_at, revoked_at
            FROM api_keys WHERE open_id = %s ORDER BY created_at DESC
            """,
            (open_id,),
        )
    else:
        rows = db.fetchall(
            """
            SELECT id, key_prefix, open_id, label, scopes, created_at, last_used_at, revoked_at
            FROM api_keys ORDER BY created_at DESC
            """
        )
    return [dict(r) for r in rows]


def has_any_api_keys() -> bool:
    """Return True if at least one active API key exists in the DB."""
    from server.db import get_db
    db = get_db()
    if db is None:
        return False
    row = db.fetchone("SELECT 1 FROM api_keys WHERE revoked_at IS NULL LIMIT 1")
    return row is not None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _extract_key(request: Request, x_api_key: str | None = Header(None)) -> str | None:
    """Extract API key from header or query param."""
    if x_api_key:
        return x_api_key
    # Also accept ?api_key= for browser-friendly download links
    return request.query_params.get("api_key")


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None),
) -> dict:
    """FastAPI dependency — require a valid API key.

    Falls back to ``RUN_TOKEN`` if no API keys exist yet in the DB
    (backwards compatibility for the transition period).

    Returns the key record (open_id, scopes, label).
    """
    raw_key = _extract_key(request, x_api_key)

    # If no API keys exist in DB yet, fall back to RUN_TOKEN
    if not has_any_api_keys():
        from server.config import settings
        if settings.run_token:
            x_run_token = request.headers.get("x-run-token")
            if x_run_token == settings.run_token:
                return {"open_id": "system", "scopes": "admin", "label": "RUN_TOKEN (legacy)"}
            if not raw_key:
                raise HTTPException(status_code=403, detail="X-API-Key or X-Run-Token header required")
        elif not raw_key:
            return {"open_id": "anonymous", "scopes": "admin", "label": "no auth configured"}

    if not raw_key:
        raise HTTPException(status_code=403, detail="X-API-Key header required")

    record = verify_api_key(raw_key)
    if record is None:
        log.warning("API key rejected (invalid or revoked)")
        raise HTTPException(status_code=403, detail="Invalid or revoked API key")

    return record


def require_scope(scope: str):
    """Factory for FastAPI dependencies that require a specific scope.

    Usage::

        @router.post("/run", dependencies=[Depends(require_scope("runs:trigger"))])
    """
    async def _check(
        request: Request,
        x_api_key: str | None = Header(None),
    ) -> dict:
        record = await require_api_key(request, x_api_key)
        user_scopes = {s.strip() for s in record.get("scopes", "").split(",") if s.strip()}
        if "admin" in user_scopes:
            return record  # admin scope grants everything
        if scope not in user_scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scope: {scope}",
            )
        return record

    return _check
