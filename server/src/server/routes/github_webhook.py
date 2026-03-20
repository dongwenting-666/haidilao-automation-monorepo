"""GitHub webhook receiver for issue events.

Listens for issue/comment/label events and writes a trigger file
so the agent cron can pick up changes within its next poll cycle.

Routes:
    POST /api/github/webhook  → receive GitHub webhook events
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])

TRIGGER_FILE = Path("/tmp/github-issue-triggers.json")


def _get_webhook_secret() -> str:
    """Return the configured webhook secret, read lazily at request time.

    Reading at import time means the module-level value is frozen to whatever
    the environment holds when the module first loads (before launchd env vars are
    visible under some startup orderings). Lazy reads always see the live value.
    """
    from server.config import settings
    return settings.github_webhook_secret

# Events we care about
_RELEVANT_ACTIONS = {
    "issues": {"opened", "edited", "labeled", "unlabeled", "closed", "reopened"},
    "issue_comment": {"created", "edited"},
}


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not secret:
        return True  # no secret configured, skip verification
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _append_trigger(event: dict) -> None:
    """Append an event to the trigger file (JSON lines)."""
    triggers: list[dict] = []
    if TRIGGER_FILE.exists():
        try:
            triggers = json.loads(TRIGGER_FILE.read_text())
            if not isinstance(triggers, list):
                triggers = []
        except (json.JSONDecodeError, OSError):
            triggers = []

    triggers.append(event)

    # Keep only last 50 events to prevent file bloat
    if len(triggers) > 50:
        triggers = triggers[-50:]

    TRIGGER_FILE.write_text(json.dumps(triggers, indent=2))


@router.post("/api/github/webhook")
async def github_webhook(request: Request):
    body = await request.body()

    # Verify signature if secret is configured
    signature = request.headers.get("X-Hub-Signature-256", "")
    webhook_secret = _get_webhook_secret()
    if webhook_secret and not _verify_signature(body, signature, webhook_secret):
        logger.warning("GitHub webhook: invalid signature")
        return JSONResponse({"error": "Invalid signature"}, status_code=401)

    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type == "ping":
        return {"ok": True, "msg": "pong"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    action = payload.get("action", "")
    relevant_actions = _RELEVANT_ACTIONS.get(event_type, set())

    if action not in relevant_actions:
        return {"ok": True, "msg": f"ignored {event_type}.{action}"}

    # Extract useful info
    issue = payload.get("issue", {})
    comment = payload.get("comment", {})
    sender = payload.get("sender", {}).get("login", "unknown")

    # Skip events from our own bot to avoid loops
    # (agent comments via gh CLI will come from the PAT owner)
    # We don't filter here — the cron handles dedup by checking last commenter

    trigger = {
        "event": event_type,
        "action": action,
        "issue_number": issue.get("number"),
        "issue_title": issue.get("title", ""),
        "sender": sender,
        "timestamp": time.time(),
    }

    if comment:
        trigger["comment_id"] = comment.get("id")
        trigger["comment_body_preview"] = comment.get("body", "")[:200]

    if action in ("labeled", "unlabeled"):
        label = payload.get("label", {})
        trigger["label"] = label.get("name", "")

    _append_trigger(trigger)
    logger.info(
        "GitHub webhook: %s.%s on #%s by %s",
        event_type, action, issue.get("number"), sender,
    )

    return {"ok": True, "event": f"{event_type}.{action}"}
