"""Feishu/Lark event receiver for simple bot auto-reply flows."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from server.config import settings
from server.lark_autoreply import generate_auto_reply

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lark"])

_SEEN_EVENTS_FILE = Path("/tmp/lark-seen-events.json")
_MAX_SEEN_EVENTS = 500


def _load_seen_events() -> list[str]:
    if not _SEEN_EVENTS_FILE.exists():
        return []
    try:
        data = json.loads(_SEEN_EVENTS_FILE.read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _remember_event(event_id: str) -> bool:
    seen = _load_seen_events()
    if event_id in seen:
        return False
    seen.append(event_id)
    if len(seen) > _MAX_SEEN_EVENTS:
        seen = seen[-_MAX_SEEN_EVENTS:]
    _SEEN_EVENTS_FILE.write_text(json.dumps(seen))
    return True


def _allowed_chat_ids() -> set[str]:
    raw = settings.lark_bot_auto_reply_chat_ids.strip()
    if not raw:
        return set()
    return {chat_id.strip() for chat_id in raw.split(",") if chat_id.strip()}


def _message_content(event: dict) -> dict:
    content = event.get("message", {}).get("content", "")
    if not content:
        return {}
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _message_mentions_bot(event: dict) -> bool:
    bot_open_id = settings.lark_bot_open_id.strip()
    mentions = event.get("mentions") or []
    for mention in mentions:
        mention_id = mention.get("id", {}).get("open_id", "")
        if bot_open_id and mention_id == bot_open_id:
            return True

    content = event.get("message", {}).get("content", "")
    if bot_open_id and isinstance(content, str):
        needle = f'user_id="{bot_open_id}"'
        if needle in content:
            return True

    text = _message_content(event).get("text", "")
    return isinstance(text, str) and "<at " in text


@router.post("/api/lark/events")
async def lark_events(request: Request):
    body = await request.json()
    logger.warning(
        "Lark callback received type=%s event_type=%s header=%s",
        body.get("type"),
        (body.get("header") or {}).get("event_type"),
        body.get("header") or {},
    )

    if body.get("type") == "url_verification":
        token = body.get("token", "")
        configured = settings.lark_event_verification_token.strip()
        if configured and token != configured:
            return JSONResponse({"error": "invalid verification token"}, status_code=401)
        return {"challenge": body.get("challenge", "")}

    header = body.get("header", {})
    event = body.get("event", {})
    event_id = header.get("event_id", "")
    event_type = header.get("event_type", "")
    body_type = body.get("type")
    if body_type and body_type != "event_callback":
        logger.info("Ignored Lark callback type=%s", body_type)
        return {"ok": True, "ignored": "unsupported_type"}
    if event_type != "im.message.receive_v1":
        logger.info("Ignored Lark event_id=%s event_type=%s", event_id, event_type or "unknown_event")
        return {"ok": True, "ignored": event_type or "unknown_event"}

    if event_id and not _remember_event(event_id):
        logger.info("Ignored duplicate Lark event_id=%s", event_id)
        return {"ok": True, "ignored": "duplicate"}

    if not settings.lark_bot_auto_reply_enabled_bool:
        logger.info("Ignored Lark event_id=%s reason=auto_reply_disabled", event_id)
        return {"ok": True, "ignored": "auto_reply_disabled"}

    chat_id = event.get("message", {}).get("chat_id", "")
    allowed_chats = _allowed_chat_ids()
    if allowed_chats and chat_id not in allowed_chats:
        logger.info("Ignored Lark event_id=%s reason=chat_not_whitelisted chat_id=%s", event_id, chat_id)
        return {"ok": True, "ignored": "chat_not_whitelisted"}

    if event.get("message", {}).get("chat_type") != "group":
        logger.info("Ignored Lark event_id=%s reason=not_group chat_type=%s", event_id, event.get("message", {}).get("chat_type"))
        return {"ok": True, "ignored": "not_group"}

    if not _message_mentions_bot(event):
        logger.warning(
            "Proceeding without explicit mention match for event_id=%s chat_id=%s content=%s",
            event_id,
            chat_id,
            event.get("message", {}).get("content", ""),
        )

    sender_open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
    if sender_open_id and sender_open_id == settings.lark_bot_open_id.strip():
        logger.info("Ignored Lark event_id=%s reason=self_message", event_id)
        return {"ok": True, "ignored": "self_message"}

    try:
        from lark_client import LarkClient

        message_id = event.get("message", {}).get("message_id", "")
        reply_text = generate_auto_reply(_message_content(event))
        logger.warning("Auto-reply event_id=%s chat_id=%s reply=%s", event_id, chat_id, reply_text)
        with LarkClient(
            app_id=settings.lark_app_id,
            app_secret=settings.lark_app_secret,
        ) as client:
            client.send_text(reply_text, chat_id=chat_id)
        logger.info("Auto-replied in chat %s for event %s", chat_id, event_id)
        return {"ok": True, "replied": True}
    except Exception as exc:
        logger.exception("Failed to auto-reply to Lark event")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
