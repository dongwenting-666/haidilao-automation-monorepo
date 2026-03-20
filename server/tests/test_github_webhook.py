"""Tests for server.routes.github_webhook.

Coverage:
- _verify_signature: valid/invalid/missing/no-secret cases
- _append_trigger: normal append, rotation at 50, corrupt file recovery
- Endpoint integration: ping, valid event, invalid signature, unsupported event
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── _verify_signature ─────────────────────────────────────────────────────────


class TestVerifySignature:
    def _sig(self, payload: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_returns_true(self):
        from server.routes.github_webhook import _verify_signature
        payload = b'{"action": "opened"}'
        secret = "my-webhook-secret"
        sig = self._sig(payload, secret)
        assert _verify_signature(payload, sig, secret) is True

    def test_invalid_signature_returns_false(self):
        from server.routes.github_webhook import _verify_signature
        payload = b'{"action": "opened"}'
        assert _verify_signature(payload, "sha256=badhash", "real-secret") is False

    def test_missing_sha256_prefix_returns_false(self):
        from server.routes.github_webhook import _verify_signature
        payload = b'{"action": "opened"}'
        secret = "secret"
        raw_hex = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        # No "sha256=" prefix
        assert _verify_signature(payload, raw_hex, secret) is False

    def test_empty_signature_returns_false(self):
        from server.routes.github_webhook import _verify_signature
        assert _verify_signature(b"data", "", "secret") is False

    def test_no_secret_bypasses_verification(self):
        """When secret is empty, verification is skipped (returns True)."""
        from server.routes.github_webhook import _verify_signature
        # Even a bad signature passes when secret is ""
        assert _verify_signature(b"data", "sha256=badhash", "") is True

    def test_wrong_payload_fails_verification(self):
        from server.routes.github_webhook import _verify_signature
        secret = "secret"
        sig = self._sig(b"original", secret)
        assert _verify_signature(b"tampered", sig, secret) is False


# ── _append_trigger ───────────────────────────────────────────────────────────


class TestAppendTrigger:
    def test_creates_file_if_not_exists(self, tmp_path):
        from server.routes import github_webhook as mod
        trigger_file = tmp_path / "triggers.json"
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            mod._append_trigger({"event": "issues", "action": "opened"})
        data = json.loads(trigger_file.read_text())
        assert len(data) == 1
        assert data[0]["event"] == "issues"

    def test_appends_to_existing_file(self, tmp_path):
        from server.routes import github_webhook as mod
        trigger_file = tmp_path / "triggers.json"
        trigger_file.write_text(json.dumps([{"event": "first"}]))
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            mod._append_trigger({"event": "second"})
        data = json.loads(trigger_file.read_text())
        assert len(data) == 2
        assert data[1]["event"] == "second"

    def test_rotates_to_50_events_max(self, tmp_path):
        from server.routes import github_webhook as mod
        trigger_file = tmp_path / "triggers.json"
        # Pre-fill 50 events
        existing = [{"event": f"e{i}"} for i in range(50)]
        trigger_file.write_text(json.dumps(existing))
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            mod._append_trigger({"event": "new"})
        data = json.loads(trigger_file.read_text())
        assert len(data) == 50
        assert data[-1]["event"] == "new"
        assert data[0]["event"] == "e1"  # oldest dropped

    def test_recovers_from_corrupt_file(self, tmp_path):
        from server.routes import github_webhook as mod
        trigger_file = tmp_path / "triggers.json"
        trigger_file.write_text("NOT VALID JSON{{{")
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            mod._append_trigger({"event": "recover"})
        data = json.loads(trigger_file.read_text())
        assert len(data) == 1
        assert data[0]["event"] == "recover"

    def test_recovers_from_non_list_json(self, tmp_path):
        from server.routes import github_webhook as mod
        trigger_file = tmp_path / "triggers.json"
        trigger_file.write_text('{"not": "a list"}')
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            mod._append_trigger({"event": "new"})
        data = json.loads(trigger_file.read_text())
        assert len(data) == 1


# ── Endpoint integration ──────────────────────────────────────────────────────


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@pytest.fixture()
def client():
    from server.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestWebhookEndpoint:
    def test_ping_event_returns_pong(self, client, tmp_path):
        from server.routes import github_webhook as mod
        with patch.object(mod, "TRIGGER_FILE", tmp_path / "t.json"):
            with patch.object(mod, "_get_webhook_secret", return_value=""):
                resp = client.post(
                    "/api/github/webhook",
                    content=b"{}",
                    headers={"X-GitHub-Event": "ping"},
                )
        assert resp.status_code == 200
        assert resp.json()["msg"] == "pong"

    def test_valid_issue_event_creates_trigger(self, client, tmp_path):
        from server.routes import github_webhook as mod
        secret = "test-secret"
        payload = json.dumps({
            "action": "opened",
            "issue": {"number": 42, "title": "Bug report"},
            "sender": {"login": "dev"},
        }).encode()
        sig = _sign(payload, secret)
        trigger_file = tmp_path / "triggers.json"
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            with patch.object(mod, "_get_webhook_secret", return_value=secret):
                resp = client.post(
                    "/api/github/webhook",
                    content=payload,
                    headers={
                        "X-GitHub-Event": "issues",
                        "X-Hub-Signature-256": sig,
                    },
                )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        data = json.loads(trigger_file.read_text())
        assert data[0]["issue_number"] == 42

    def test_invalid_signature_returns_401(self, client, tmp_path):
        from server.routes import github_webhook as mod
        payload = b'{"action": "opened"}'
        with patch.object(mod, "TRIGGER_FILE", tmp_path / "t.json"):
            with patch.object(mod, "_get_webhook_secret", return_value="real-secret"):
                resp = client.post(
                    "/api/github/webhook",
                    content=payload,
                    headers={
                        "X-GitHub-Event": "issues",
                        "X-Hub-Signature-256": "sha256=badhash",
                    },
                )
        assert resp.status_code == 401

    def test_unsupported_event_ignored(self, client, tmp_path):
        from server.routes import github_webhook as mod
        payload = json.dumps({"action": "starred"}).encode()
        trigger_file = tmp_path / "t.json"
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            with patch.object(mod, "_get_webhook_secret", return_value=""):
                resp = client.post(
                    "/api/github/webhook",
                    content=payload,
                    headers={"X-GitHub-Event": "watch"},
                )
        assert resp.status_code == 200
        assert "ignored" in resp.json().get("msg", "")
        assert not trigger_file.exists()

    def test_no_secret_allows_request(self, client, tmp_path):
        """When GITHUB_WEBHOOK_SECRET is empty, any request passes."""
        from server.routes import github_webhook as mod
        payload = json.dumps({
            "action": "created",
            "issue": {"number": 1, "title": "x"},
            "sender": {"login": "bot"},
        }).encode()
        trigger_file = tmp_path / "t.json"
        with patch.object(mod, "TRIGGER_FILE", trigger_file):
            with patch.object(mod, "_get_webhook_secret", return_value=""):
                resp = client.post(
                    "/api/github/webhook",
                    content=payload,
                    headers={
                        "X-GitHub-Event": "issue_comment",
                        "X-Hub-Signature-256": "",
                    },
                )
        assert resp.status_code == 200

    def test_invalid_json_returns_400(self, client, tmp_path):
        from server.routes import github_webhook as mod
        with patch.object(mod, "TRIGGER_FILE", tmp_path / "t.json"):
            with patch.object(mod, "_get_webhook_secret", return_value=""):
                resp = client.post(
                    "/api/github/webhook",
                    content=b"not json{{{",
                    headers={"X-GitHub-Event": "issues"},
                )
        assert resp.status_code == 400
