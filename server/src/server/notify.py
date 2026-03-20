"""Lark notification helpers for the automation server.

Notification targets are configured per-command in ``server/notify.toml``.

Chat IDs are defined once as named aliases in the ``[chats]`` section and
referenced by name in per-command entries::

    [chats]
    hongming    = "oc_78f29489a577f10e36ebf989bccdcc83"
    store_hours = "oc_9fe9a845d25c1e07a58a1230cbb04b5d"

    [daily-report]
    chat = "hongming"          # resolved via [chats]

    [ksb1]
    user_id = "ou_xxxxxxxx"   # DM fallback

Lark credentials (LARK_APP_ID, LARK_APP_SECRET) must be set in .env.
If either the credentials or a command's target are not configured, that
notification is a silent no-op.

Usage:
    from server.notify import notify_run_complete, notify_text
    notify_run_complete(run)              # called automatically after every run
    notify_text("daily-report", "Hello") # send a one-off message
    chat_id_for("hongming")              # resolve a named alias directly
"""

from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.routes.runs import Run

log = logging.getLogger(__name__)

_NOTIFY_CONFIG = Path(__file__).resolve().parents[4] / "notify.toml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load and cache the full notify.toml (per-command entries only; [chats] is
    handled by ``lark_client.notify_config._load_chats()``).

    Results are cached for the lifetime of the process.
    **Changes to notify.toml require a server restart to take effect.**

    Returns empty dict if the file doesn't exist or can't be parsed.
    """
    if not _NOTIFY_CONFIG.exists():
        log.debug("notify.toml not found at %s", _NOTIFY_CONFIG)
        return {}
    try:
        with open(_NOTIFY_CONFIG, "rb") as f:
            return tomllib.load(f)
    except Exception:
        log.exception("Failed to load notify.toml")
        return {}


def chat_id_for(alias: str) -> str | None:
    """Resolve a named chat alias from the ``[chats]`` section of notify.toml.

    Delegates to ``lark_client.notify_config`` which owns the canonical
    implementation and caches results for the process lifetime.
    """
    from lark_client.notify_config import chat_id_for as _chat_id_for
    return _chat_id_for(alias)


def _target_for(command: str) -> tuple[str | None, str | None]:
    """Return (chat_id, user_id) for a command, or (None, None) if not configured."""
    config = _load_config()
    entry = config.get(command, {})

    # Prefer named alias → raw chat_id fallback → user_id
    chat_alias = entry.get("chat")
    if chat_alias:
        chat_id = chat_id_for(chat_alias)
        if chat_id is None:
            log.warning(
                "notify.toml [%s]: chat alias %r not found in [chats]", command, chat_alias
            )
        return chat_id, None

    chat_id = entry.get("chat_id") or None
    user_id = entry.get("user_id") or None
    if chat_id and user_id:
        log.warning(
            "notify.toml [%s]: both chat_id and user_id set — using chat_id", command
        )
        user_id = None
    return chat_id, user_id


def _client():
    """Return a LarkClient, or None if credentials are not configured."""
    from server.config import settings
    if not settings.lark_enabled:
        return None
    from lark_client import LarkClient
    return LarkClient(app_id=settings.lark_app_id, app_secret=settings.lark_app_secret)


def notify_run_complete(run: "Run") -> None:
    """Send a Lark card summarising a completed run.

    Silent no-op if Lark is not configured or the command has no target
    in notify.toml.
    """
    from server.config import settings
    if not settings.lark_enabled:
        return

    chat_id, user_id = _target_for(run.command)
    if not chat_id and not user_id:
        log.debug("notify: no target for command %r, skipping", run.command)
        return

    success = run.status.value == "success"
    color = "green" if success else "red"
    icon = "✅" if success else "❌"

    duration = ""
    if run.finished_at and run.started_at:
        secs = (run.finished_at - run.started_at).total_seconds()
        duration = f"  ⏱ {secs:.0f}s"

    title = f"{icon} {run.command} — {run.status.value}{duration}"

    lines = []
    if run.logs:
        tail = "\n".join(run.logs.strip().splitlines()[-8:])
        lines.append(f"```\n{tail}\n```")
    content = "\n".join(lines) if lines else "_No output_"

    try:
        client = _client()
        if client is None:
            return
        with client:
            client.send_card(
                title=title,
                content=content,
                color=color,
                chat_id=chat_id,
                user_id=user_id,
            )
        log.info("Lark notification sent for run %s (%s)", run.id, run.status.value)
    except Exception:
        log.exception("Failed to send Lark notification for run %s", run.id)


def notify_daily_report_file(report_path: "Path") -> None:
    """Send the generated daily report xlsx to the production accounting chat.

    Sends a card header first (so the file doesn't get lost in conversation),
    then attaches the xlsx file.  Reads ``production_accounting_report_chat``
    from notify.toml [chats].  Silent no-op if Lark is not configured or the
    alias is missing.
    """
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id = chat_id_for("production_accounting_report_chat")
    if not chat_id:
        log.warning("notify: 'production_accounting_report_chat' alias not found in notify.toml [chats], skipping file send")
        return

    # Parse report date from filename: database_report_YYYY_MM_DD.xlsx
    date_str = "unknown date"
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})", report_path.name)
    if m:
        date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    now = datetime.now(ZoneInfo("America/Vancouver")).strftime("%Y-%m-%d %H:%M")

    try:
        client = _client()
        if client is None:
            return
        with client:
            # 1. Card header — anchors the file in conversation
            client.send_card(
                title=f"📊 海外门店经营日报 · {date_str}",
                content=(
                    f"**日报文件已生成**，数据日期：**{date_str}**\n\n"
                    f"生成时间：{now} (Vancouver)\n\n"
                    "---\n"
                    "👇 附件见下方"
                ),
                color="blue",
                chat_id=chat_id,
            )
            # 2. The xlsx file itself
            client.send_file(
                report_path,
                filename=report_path.name,
                chat_id=chat_id,
                file_type="xlsx",
            )
        log.info("Daily report card + file sent to production_accounting_report_chat: %s", report_path.name)
    except Exception:
        log.exception("Failed to send daily report file to Lark")


def notify_text(command: str, text: str) -> None:
    """Send a plain text message to the target configured for *command*.

    Silent no-op if Lark is not configured or no target is set.
    """
    from server.config import settings
    if not settings.lark_enabled:
        return

    chat_id, user_id = _target_for(command)
    if not chat_id and not user_id:
        return

    try:
        client = _client()
        if client is None:
            return
        with client:
            client.send_text(text, chat_id=chat_id, user_id=user_id)
    except Exception:
        log.exception("Failed to send Lark text notification for %r", command)
