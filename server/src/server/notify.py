"""Lark notification helpers for the automation server.

Notification targets are configured per-command in ``server/notify.toml``.

Chat IDs are defined once as named aliases in the ``[chats]`` section and
referenced by name in per-command entries::

    [chats]
    hongming    = "oc_..."   # see server/notify.toml for actual IDs
    store_hours = "oc_..."

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

_NOTIFY_CONFIG = Path(__file__).resolve().parents[2] / "notify.toml"


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


def _target_for(command: str) -> tuple[str | None, str | None, bool]:
    """Return (chat_id, user_id, on_failure_only) for a command.

    ``on_failure_only=True`` means the run-complete card is suppressed on success
    (set via ``on_failure_only = true`` in the command's notify.toml section).
    """
    config = _load_config()
    entry = config.get(command, {})
    on_failure_only: bool = bool(entry.get("on_failure_only", False))

    # Prefer named alias → raw chat_id fallback → user_id
    chat_alias = entry.get("chat")
    if chat_alias:
        chat_id = chat_id_for(chat_alias)
        if chat_id is None:
            log.warning(
                "notify.toml [%s]: chat alias %r not found in [chats]", command, chat_alias
            )
        return chat_id, None, on_failure_only

    chat_id = entry.get("chat_id") or None
    user_id = entry.get("user_id") or None
    if chat_id and user_id:
        log.warning(
            "notify.toml [%s]: both chat_id and user_id set — using chat_id", command
        )
        user_id = None
    return chat_id, user_id, on_failure_only


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
    in notify.toml.  If ``on_failure_only = true`` is set for the command,
    the card is also suppressed on success.
    """
    from server.config import settings
    if not settings.lark_enabled:
        return

    chat_id, user_id, on_failure_only = _target_for(run.command)
    if not chat_id and not user_id:
        log.debug("notify: no target for command %r, skipping", run.command)
        return

    success = run.status.value == "success"
    if on_failure_only and success:
        log.debug("notify: on_failure_only=true for %r, suppressing success card", run.command)
        return
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


def notify_daily_report_file(report_path: "Path", target_chat: str = "production_accounting_report_chat") -> None:
    """Send the generated daily report xlsx to a Lark chat.

    Sends a card header first (so the file doesn't get lost in conversation),
    then attaches the xlsx file.

    *target_chat* is a named alias from ``server/notify.toml [chats]``.
    Defaults to ``production_accounting_report_chat`` for the scheduler cron.
    Pass any alias (e.g. ``"hongming"``) for testing/debug delivery.
    Silent no-op if Lark is not configured or the alias is missing.
    """
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id = chat_id_for(target_chat)
    if not chat_id:
        log.warning("notify: '%s' alias not found in notify.toml [chats], skipping file send", target_chat)
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

            # 3. Sheet screenshots — each sheet as a PNG image
            try:
                from server.sheet_screenshot import render_all_sheets
                sheets = render_all_sheets(report_path)
                for sheet_name, png_bytes in sheets:
                    try:
                        client.send_image(png_bytes, chat_id=chat_id)
                        log.info("Sent screenshot for sheet '%s'", sheet_name)
                    except Exception:
                        log.exception("Failed to send screenshot for sheet '%s'", sheet_name)
            except Exception:
                log.exception("Failed to render sheet screenshots")

        log.info("Daily report card + file + screenshots sent to %s: %s", target_chat, report_path.name)
    except Exception:
        log.exception("Failed to send daily report file to Lark")


def notify_daily_report_screenshots(
    report_path: "Path",
    target_chat: str = "finance_study_group",
    sheet_names: tuple[str, ...] = ("对比上年表", "分时段-上报"),
) -> None:
    """Send selected sheet screenshots to a secondary chat group.

    Only sends PNG images of the specified sheets — no card, no xlsx file.
    """
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id = chat_id_for(target_chat)
    if not chat_id:
        log.warning("notify: '%s' alias not found, skipping screenshot send", target_chat)
        return

    try:
        from server.sheet_screenshot import render_all_sheets

        client = _client()
        if client is None:
            return

        sheets = render_all_sheets(report_path)
        with client:
            for sheet_name, png_bytes in sheets:
                if sheet_name in sheet_names:
                    client.send_image(png_bytes, chat_id=chat_id)
                    log.info("Sent '%s' screenshot to %s", sheet_name, target_chat)

        log.info("Daily report screenshots sent to %s", target_chat)
    except Exception:
        log.exception("Failed to send daily report screenshots to %s", target_chat)


def notify_ksb1_file(
    report_path: "Path",
    *,
    target_chat: str = "production_accounting_report_chat",
    triggered_by_open_id: str = "",
    triggered_by_name: str = "",
) -> None:
    """Send the KSB1 report xlsx to a Lark chat and @mention the requester.

    Parameters
    ----------
    report_path:
        Path to the generated KSB1 XLSX report.
    target_chat:
        Chat alias from notify.toml [chats].  Defaults to the production group.
    triggered_by_open_id:
        open_id of the user who triggered the run.  Used for @mention.
        Pass empty string to skip the mention.
    triggered_by_name:
        Display name for the mention fallback label.
    """
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id = chat_id_for(target_chat)
    if not chat_id:
        log.warning(
            "notify: '%s' alias not found in notify.toml [chats], skipping ksb1 file send",
            target_chat,
        )
        return

    # Parse YYYY-MM from filename: {year_month}_KSB1_检查报告_{timestamp}.XLSX
    import re
    year_month = "unknown"
    m = re.search(r"(\d{4}-\d{2})", report_path.name)
    if m:
        year_month = m.group(1)

    now = datetime.now(ZoneInfo("America/Vancouver")).strftime("%Y-%m-%d %H:%M")

    try:
        client = _client()
        if client is None:
            return
        with client:
            # Build mention header using Lark rich-text (post) format
            if triggered_by_open_id:
                # Send a rich-text message that @mentions the requester
                mention_content = {
                    "zh_cn": {
                        "title": f"📊 KSB1 账务核查报告 · {year_month}",
                        "content": [
                            [
                                {"tag": "text", "text": "报告已生成（"},
                                {
                                    "tag": "at",
                                    "user_id": triggered_by_open_id,
                                    "user_name": triggered_by_name or "操作员",
                                },
                                {
                                    "tag": "text",
                                    "text": f" 触发）\n数据周期：{year_month}  ·  生成时间：{now} (Vancouver)\n附件见下方 👇",
                                },
                            ]
                        ],
                    }
                }
                client._post(
                    f"/im/v1/messages?receive_id_type=chat_id",
                    {
                        "receive_id": chat_id,
                        "msg_type": "post",
                        "content": json.dumps(mention_content),
                    },
                )
            else:
                # No requester info — send a plain card header
                client.send_card(
                    title=f"📊 KSB1 账务核查报告 · {year_month}",
                    content=(
                        f"**报告已生成**，数据周期：**{year_month}**\n\n"
                        f"生成时间：{now} (Vancouver)\n\n"
                        "---\n👇 附件见下方"
                    ),
                    color="blue",
                    chat_id=chat_id,
                )

            # Send the xlsx file
            client.send_file(
                report_path,
                filename=report_path.name,
                chat_id=chat_id,
                file_type="xlsx",
            )

        log.info(
            "KSB1 report sent to %s: %s (triggered_by=%s)",
            target_chat,
            report_path.name,
            triggered_by_open_id or "—",
        )
    except Exception:
        log.exception("Failed to send KSB1 report to Lark")


def notify_travel_budget_file(
    report_path: "Path",
    *,
    target_chat: str = "hongming",
    report_month: int = 0,
    year: int = 0,
) -> None:
    """Send the travel budget report xlsx to a Lark chat."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id = chat_id_for(target_chat)
    if not chat_id:
        log.warning("notify: '%s' alias not found, skipping travel budget send", target_chat)
        return

    now = datetime.now(ZoneInfo("America/Vancouver")).strftime("%Y-%m-%d %H:%M")
    period = f"{year}年1-{report_month}月" if year and report_month else "unknown"

    try:
        client = _client()
        if client is None:
            return

        with client:
            client.send_card(
                title=f"✈️ 差旅费预算明细 · {period}",
                content=(
                    f"**报告已生成**，数据周期：**{period}**\n\n"
                    f"生成时间：{now} (Vancouver)\n\n"
                    "---\n👇 附件见下方"
                ),
                color="blue",
                chat_id=chat_id,
            )
            client.send_file(
                report_path,
                filename=report_path.name,
                chat_id=chat_id,
                file_type="xlsx",
            )

        log.info("Travel budget report sent to %s: %s", target_chat, report_path.name)
    except Exception:
        log.exception("Failed to send travel budget report to Lark")


def notify_text(command: str, text: str) -> None:
    """Send a plain text message to the target configured for *command*.

    Silent no-op if Lark is not configured or no target is set.
    """
    from server.config import settings
    if not settings.lark_enabled:
        return

    chat_id, user_id, _ = _target_for(command)
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
