"""Lark notification helpers for the automation server.

Call ``notify_run_complete(run)`` after a run finishes to send a card
to the configured Lark chat or user.  If Lark credentials are not set,
all calls are silent no-ops.

Usage in scheduler or elsewhere:
    from server.notify import notify_run_complete
    await asyncio.to_thread(notify_run_complete, run)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.routes.runs import Run

log = logging.getLogger(__name__)


def _client():
    """Return a LarkClient, or None if not configured."""
    from server.config import settings
    if not settings.lark_enabled:
        return None
    from lark_client import LarkClient
    return LarkClient(
        app_id=settings.lark_app_id,
        app_secret=settings.lark_app_secret,
    )


def notify_run_complete(run: "Run") -> None:
    """Send a Lark card summarising a completed run.

    Silent no-op if Lark is not configured or notification target is unset.
    """
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id, user_id = settings.lark_notify_target
    if not chat_id and not user_id:
        log.debug("Lark notify: no target configured, skipping")
        return

    success = run.status.value == "success"
    color = "green" if success else "red"
    status_icon = "✅" if success else "❌"

    duration = ""
    if run.finished_at and run.started_at:
        secs = (run.finished_at - run.started_at).total_seconds()
        duration = f"  ⏱ {secs:.0f}s"

    title = f"{status_icon} {run.command} — {run.status.value}{duration}"

    lines = []
    if run.logs:
        # Show last few lines of logs for context
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
                chat_id=chat_id or None,
                user_id=user_id or None,
            )
        log.info("Lark notification sent for run %s (%s)", run.id, run.status.value)
    except Exception:
        log.exception("Failed to send Lark notification for run %s", run.id)


def notify_text(text: str) -> None:
    """Send a plain text message to the configured Lark target.

    Silent no-op if Lark is not configured.
    """
    from server.config import settings

    if not settings.lark_enabled:
        return

    chat_id, user_id = settings.lark_notify_target
    if not chat_id and not user_id:
        return

    try:
        client = _client()
        if client is None:
            return
        with client:
            client.send_text(
                text,
                chat_id=chat_id or None,
                user_id=user_id or None,
            )
    except Exception:
        log.exception("Failed to send Lark text notification")
