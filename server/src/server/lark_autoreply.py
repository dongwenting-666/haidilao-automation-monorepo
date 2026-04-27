from __future__ import annotations

import json
import logging
import re

import httpx

from server.config import settings

logger = logging.getLogger(__name__)

_AT_TAG_RE = re.compile(r"<at\b[^>]*>.*?</at>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"\s+")
_OPENAI_BASE_URL = "https://api.openai.com/v1/chat/completions"


def _extract_plain_text(message_content: dict) -> str:
    text = message_content.get("text", "")
    if not isinstance(text, str):
        return ""
    text = _AT_TAG_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def _fallback_reply(text: str) -> str:
    lowered = text.lower()
    if not text:
        return "在，什么事？"
    if any(token in lowered for token in ("你好", "hi", "hello", "在吗", "在不在")):
        return "在，什么事？"
    if "谢谢" in text:
        return "不客气。"
    if any(token in lowered for token in ("收到", "ok", "好的", "了解")):
        return "好。"
    return settings.lark_bot_auto_reply_text.strip() or "收到，我看一下。"


def _system_prompt() -> str:
    persona_name = settings.lark_bot_auto_reply_persona_name.strip() or "董文婷"
    persona_prompt = settings.lark_bot_auto_reply_persona_prompt.strip()
    return (
        f"{persona_prompt}\n"
        f"你现在就是 {persona_name} 风格的飞书工作群助理。\n"
        "只输出最终回复内容，不要解释。\n"
        "控制在 1 到 2 句内，尽量不超过 30 个汉字。\n"
        "不要自称 AI，不要提模型，不要加引号。"
    )


def generate_auto_reply(message_content: dict) -> str:
    plain_text = _extract_plain_text(message_content)
    fallback = _fallback_reply(plain_text)
    api_key = settings.openai_api_key.strip()
    if not api_key:
        logger.info("OPENAI_API_KEY not set; using fallback auto-reply")
        return fallback

    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": plain_text or "有人在群里 @你，但是没有可读文字。"},
        ],
        "temperature": 0.4,
        "max_completion_tokens": 80,
    }

    try:
        with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
            resp = client.post(
                _OPENAI_BASE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("OpenAI auto-reply request failed")
        return fallback

    try:
        reply = data["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.warning("Unexpected OpenAI response format: %s", json.dumps(data)[:1000])
        return fallback

    if not reply:
        return fallback
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    return lines[0] if lines else fallback

