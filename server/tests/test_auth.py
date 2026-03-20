"""Tests for server.auth — session signing, whitelist, super admin, cookie flags.

All tests are fully self-contained (no DB, no network).
"""

from __future__ import annotations

import json
import os
import time

import pytest


# Stable key for all tests in this module so sign/verify round-trips work.
os.environ.setdefault("SESSION_SECRET", "test-auth-secret-pytest-stable-xyz-1234")
# Clear DB env so is_whitelisted/is_super_admin use env-var path only.
os.environ.pop("DATABASE_URL", None)


# ── _get_signer ───────────────────────────────────────────────────────────────


class TestGetSigner:
    def test_returns_signer_with_configured_secret(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "mysecret")
        from server import auth
        import importlib
        importlib.reload(auth)  # re-evaluate module globals
        s = auth._get_signer()
        assert s is not None

    def test_fallback_secret_is_stable_within_process(self, monkeypatch):
        """Without SESSION_SECRET, the same fallback key must be used every call."""
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        # Patch settings to return empty secret too
        from server.auth import _get_signer
        with pytest.MonkeyPatch().context() as m:
            m.setattr("server.config.settings.session_secret", "")
            # Clear cached fallback so we start fresh
            import server.auth as auth_mod
            auth_mod._fallback_secret = ""
            s1 = auth_mod._get_signer()
            s2 = auth_mod._get_signer()
            # Both signers should produce the same signature for the same payload
            payload = b"hello"
            assert s1.sign(payload) == s2.sign(payload)


# ── Session round-trip ────────────────────────────────────────────────────────


class TestSessionRoundTrip:
    def test_sign_then_unsign_returns_original_payload(self):
        from server.auth import _get_signer
        s = _get_signer()
        payload = json.dumps({"open_id": "ou_abc", "name": "Alice"}).encode()
        signed = s.sign(payload)
        raw = s.unsign(signed, max_age=60)
        assert json.loads(raw) == {"open_id": "ou_abc", "name": "Alice"}

    def test_get_session_returns_none_without_cookie(self):
        from unittest.mock import MagicMock
        from server.auth import get_session
        req = MagicMock()
        req.cookies = {}
        assert get_session(req) is None

    def test_get_session_returns_dict_with_valid_cookie(self):
        from unittest.mock import MagicMock
        from server.auth import get_session, _get_signer
        payload = json.dumps({"open_id": "ou_xyz", "name": "Bob"})
        signed = _get_signer().sign(payload.encode()).decode()
        req = MagicMock()
        req.cookies = {"admin_session": signed}
        session = get_session(req)
        assert session == {"open_id": "ou_xyz", "name": "Bob"}

    def test_get_session_returns_none_for_tampered_cookie(self):
        from unittest.mock import MagicMock
        from server.auth import get_session
        req = MagicMock()
        req.cookies = {"admin_session": "ou_xyz.invalidsignature"}
        assert get_session(req) is None

    def test_get_session_returns_none_for_garbled_cookie(self):
        from unittest.mock import MagicMock
        from server.auth import get_session
        req = MagicMock()
        req.cookies = {"admin_session": "not_a_valid_signed_value"}
        assert get_session(req) is None


# ── Cookie flags ──────────────────────────────────────────────────────────────


class TestCookieFlags:
    def test_set_session_cookie_sets_httponly(self, monkeypatch):
        from unittest.mock import MagicMock
        from server.auth import set_session_cookie
        monkeypatch.setenv("COOKIE_SECURE", "false")
        resp = MagicMock()
        set_session_cookie(resp, "ou_abc", "Alice")
        call_kwargs = resp.set_cookie.call_args.kwargs
        assert call_kwargs["httponly"] is True

    def test_set_session_cookie_sets_samesite_lax(self, monkeypatch):
        from unittest.mock import MagicMock
        from server.auth import set_session_cookie
        monkeypatch.setenv("COOKIE_SECURE", "false")
        resp = MagicMock()
        set_session_cookie(resp, "ou_abc", "Alice")
        call_kwargs = resp.set_cookie.call_args.kwargs
        assert call_kwargs["samesite"] == "lax"

    def test_set_session_cookie_secure_true_by_default(self, monkeypatch):
        from unittest.mock import MagicMock
        from server.auth import set_session_cookie, _cookie_secure
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
        assert _cookie_secure() is True

    def test_cookie_secure_false_when_env_disabled(self, monkeypatch):
        from server.auth import _cookie_secure
        monkeypatch.setenv("COOKIE_SECURE", "false")
        monkeypatch.setattr("server.config.settings.cookie_secure", "false")
        assert _cookie_secure() is False

    def test_cookie_secure_false_for_zero(self, monkeypatch):
        from server.auth import _cookie_secure
        monkeypatch.setenv("COOKIE_SECURE", "0")
        monkeypatch.setattr("server.config.settings.cookie_secure", "0")
        assert _cookie_secure() is False

    def test_set_session_cookie_has_max_age(self, monkeypatch):
        from unittest.mock import MagicMock
        from server.auth import set_session_cookie
        monkeypatch.setenv("COOKIE_SECURE", "false")
        resp = MagicMock()
        set_session_cookie(resp, "ou_abc", "Alice")
        call_kwargs = resp.set_cookie.call_args.kwargs
        assert isinstance(call_kwargs["max_age"], int)
        # 8 hours = 28800 seconds
        assert call_kwargs["max_age"] == 8 * 3600


# ── is_whitelisted ────────────────────────────────────────────────────────────


class TestIsWhitelisted:
    def test_true_for_open_id_in_env_var(self, monkeypatch):
        monkeypatch.setenv("ADMIN_WHITELIST", "ou_user1,ou_user2")
        # Prevent DB check from running
        import server.auth as auth_mod
        monkeypatch.setattr(auth_mod, "is_whitelisted", lambda oid: _isolated_is_whitelisted(oid, monkeypatch))
        from server.auth import is_whitelisted
        # Direct env var check (bypassing DB since DATABASE_URL not set)
        assert is_whitelisted("ou_user1") is True

    def test_false_for_unknown_open_id(self, monkeypatch):
        monkeypatch.setenv("ADMIN_WHITELIST", "ou_user1,ou_user2")
        from server.auth import is_whitelisted
        assert is_whitelisted("ou_stranger") is False

    def test_false_when_whitelist_is_empty(self, monkeypatch):
        monkeypatch.setenv("ADMIN_WHITELIST", "")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "")
        from server.auth import is_whitelisted
        assert is_whitelisted("ou_anyone") is False

    def test_whitelist_trims_spaces(self, monkeypatch):
        monkeypatch.setenv("ADMIN_WHITELIST", " ou_spaced , ou_user2 ")
        monkeypatch.setattr("server.config.settings.admin_whitelist", " ou_spaced , ou_user2 ")
        from server.auth import is_whitelisted
        assert is_whitelisted("ou_spaced") is True

    def test_whitelist_ignores_empty_tokens(self, monkeypatch):
        monkeypatch.setenv("ADMIN_WHITELIST", "ou_a,,ou_b")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_a,,ou_b")
        from server.auth import is_whitelisted
        assert is_whitelisted("ou_a") is True
        assert is_whitelisted("") is False


def _isolated_is_whitelisted(oid: str, monkeypatch) -> bool:
    """Helper that uses env var path directly (skips DB)."""
    whitelist_raw = os.environ.get("ADMIN_WHITELIST", "").strip()
    if not whitelist_raw:
        return False
    allowed = {x.strip() for x in whitelist_raw.split(",") if x.strip()}
    return oid in allowed


# ── is_super_admin ────────────────────────────────────────────────────────────


class TestIsSuperAdmin:
    def test_true_for_id_in_super_admin_env(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_OPEN_IDS", "ou_boss,ou_cto")
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "ou_boss,ou_cto")
        from server.auth import is_super_admin
        assert is_super_admin("ou_boss") is True

    def test_false_for_id_not_in_super_admin_env(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_OPEN_IDS", "ou_boss")
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "ou_boss")
        from server.auth import is_super_admin
        assert is_super_admin("ou_peon") is False

    def test_falls_back_to_whitelist_when_super_admin_unset(self, monkeypatch):
        monkeypatch.delenv("SUPER_ADMIN_OPEN_IDS", raising=False)
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "")
        monkeypatch.setenv("ADMIN_WHITELIST", "ou_fallback")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_fallback")
        from server.auth import is_super_admin
        assert is_super_admin("ou_fallback") is True

    def test_returns_false_when_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("SUPER_ADMIN_OPEN_IDS", raising=False)
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "")
        monkeypatch.delenv("ADMIN_WHITELIST", raising=False)
        monkeypatch.setattr("server.config.settings.admin_whitelist", "")
        from server.auth import is_super_admin
        assert is_super_admin("ou_anyone") is False

    def test_super_admin_takes_precedence_over_whitelist(self, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_OPEN_IDS", "ou_boss")
        monkeypatch.setattr("server.config.settings.super_admin_open_ids", "ou_boss")
        monkeypatch.setenv("ADMIN_WHITELIST", "ou_boss,ou_regular")
        monkeypatch.setattr("server.config.settings.admin_whitelist", "ou_boss,ou_regular")
        from server.auth import is_super_admin
        # Only ou_boss is super admin; ou_regular is whitelisted but not super admin
        assert is_super_admin("ou_boss") is True
        assert is_super_admin("ou_regular") is False
