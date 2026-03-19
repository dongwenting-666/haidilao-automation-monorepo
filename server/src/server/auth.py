"""Authentication helpers for the admin section.

Provides:
- Signed cookie sessions via itsdangerous
- Lark (Feishu) OAuth helpers
- require_auth FastAPI dependency
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from urllib.parse import quote, urlencode

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

logger = logging.getLogger(__name__)

# ── Session signing ───────────────────────────────────────────────────────────

_SESSION_MAX_AGE = 8 * 3600  # 8 hours
_COOKIE_NAME = "admin_session"


def _get_signer() -> TimestampSigner:
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret:
        secret = secrets.token_hex(32)
        logger.warning(
            "SESSION_SECRET not set — using a random key. "
            "Sessions will not survive server restarts. Set SESSION_SECRET in env."
        )
    return TimestampSigner(secret)


def get_session(request: Request) -> dict | None:
    """Decode the admin session cookie. Returns {open_id, name} or None."""
    cookie = request.cookies.get(_COOKIE_NAME)
    if not cookie:
        return None
    try:
        signer = _get_signer()
        raw = signer.unsign(cookie, max_age=_SESSION_MAX_AGE)
        return json.loads(raw)
    except (SignatureExpired, BadSignature, Exception):
        return None


def set_session_cookie(response, open_id: str, name: str) -> None:
    """Attach a signed session cookie to *response*."""
    payload = json.dumps({"open_id": open_id, "name": name})
    signer = _get_signer()
    signed = signer.sign(payload).decode()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=signed,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,  # only send over HTTPS
    )


def clear_session_cookie(response) -> None:
    """Remove the session cookie."""
    response.delete_cookie(key=_COOKIE_NAME, httponly=True, samesite="lax", secure=True)


# ── Whitelist ────────────────────────────────────────────────────────────────


def is_whitelisted(open_id: str) -> bool:
    """Return True if open_id is allowed admin access.

    Checks (in order):
    1. DB admin_users.whitelisted column (if DB is available)
    2. ADMIN_WHITELIST env var (bootstrap / fallback)
    """
    # DB check first
    try:
        from server.db import is_db_whitelisted
        if is_db_whitelisted(open_id):
            return True
    except Exception:
        pass

    # Env var fallback (used on first login before DB record exists)
    whitelist_raw = os.environ.get("ADMIN_WHITELIST", "")
    if not whitelist_raw.strip():
        return False
    allowed = {oid.strip() for oid in whitelist_raw.split(",") if oid.strip()}
    return open_id in allowed


# ── FastAPI dependency ────────────────────────────────────────────────────────


class LoginRequired(Exception):
    """Raised by require_auth when user is not authenticated."""

    def __init__(self, next_url: str):
        self.next_url = next_url


async def require_auth(request: Request) -> dict:
    """FastAPI dependency — raises LoginRequired if not authenticated."""
    session = get_session(request)
    if session is None:
        raise LoginRequired(str(request.url.path))
    return session


# ── Lark OAuth ───────────────────────────────────────────────────────────────

_LARK_AUTHORIZE_URL = "https://open.feishu.cn/open-apis/authen/v1/authorize"
_LARK_APP_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
_LARK_OIDC_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token"
_LARK_USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"


def _get_lark_credentials() -> tuple[str, str]:
    app_id = os.environ.get("LARK_APP_ID", "")
    app_secret = os.environ.get("LARK_APP_SECRET", "")
    return app_id, app_secret


def get_lark_auth_url(redirect_uri: str, state: str) -> str:
    """Build the Lark OAuth authorization URL."""
    app_id, _ = _get_lark_credentials()
    params = urlencode({"app_id": app_id, "redirect_uri": redirect_uri, "state": state})
    return f"{_LARK_AUTHORIZE_URL}?{params}"


async def _get_app_access_token() -> str:
    """Fetch a fresh app_access_token from Lark."""
    app_id, app_secret = _get_lark_credentials()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _LARK_APP_TOKEN_URL,
            json={"app_id": app_id, "app_secret": app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get app_access_token: {data}")
        return data["app_access_token"]


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an OAuth code for user info.

    Returns dict with keys: open_id, name, avatar_url.
    """
    app_token = await _get_app_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        # Exchange code for user access token
        token_resp = await client.post(
            _LARK_OIDC_TOKEN_URL,
            json={"grant_type": "authorization_code", "code": code},
            headers={"Authorization": f"Bearer {app_token}"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        if token_data.get("code") != 0:
            raise RuntimeError(f"Failed to exchange code: {token_data}")

        user_access_token = token_data["data"]["access_token"]

        # Fetch user info
        info_resp = await client.get(
            _LARK_USER_INFO_URL,
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        info_resp.raise_for_status()
        info_data = info_resp.json()
        if info_data.get("code") != 0:
            raise RuntimeError(f"Failed to get user info: {info_data}")

        user = info_data["data"]
        return {
            "open_id": user.get("open_id", ""),
            "name": user.get("name", user.get("en_name", "Unknown")),
            "avatar_url": user.get("avatar_url", ""),
        }
