"""Helpers for resolving named chat aliases from notify.toml.

All projects in this monorepo share ``server/notify.toml``.
The ``[chats]`` section defines human-readable aliases for Lark open_chat_ids::

    [chats]
    hongming    = "oc_..."   # see server/notify.toml for actual IDs
    store_hours = "oc_..."

Use ``chat_id_for(alias)`` anywhere you need a chat ID — no raw IDs in code.

Usage:
    from lark_client.notify_config import chat_id_for

    chat_id = chat_id_for("hongming")
    chat_id = chat_id_for("store_hours")
"""

from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    """Walk up from this file to find the monorepo root (has [tool.uv.workspace])."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        candidate = p / "pyproject.toml"
        if candidate.is_file() and "[tool.uv.workspace]" in candidate.read_text(encoding="utf-8"):
            return p
        p = p.parent
    return Path(__file__).resolve().parents[4]  # best-effort fallback


@lru_cache(maxsize=1)
def _load_chats() -> dict[str, str]:
    """Load and cache the ``[chats]`` table from ``server/notify.toml``.

    Results are cached for the lifetime of the process.
    **Changes to notify.toml require a server restart to take effect.**

    Returns empty dict if the file doesn't exist or can't be parsed.
    """
    notify_toml = _find_repo_root() / "server" / "notify.toml"
    if not notify_toml.exists():
        log.debug("notify.toml not found at %s", notify_toml)
        return {}
    try:
        with open(notify_toml, "rb") as f:
            return tomllib.load(f).get("chats", {})
    except Exception:
        log.exception("Failed to load [chats] from notify.toml")
        return {}


def chat_id_for(alias: str) -> str | None:
    """Resolve a named chat alias to its Lark open_chat_id.

    Returns the raw open_chat_id string, or None if the alias is not defined.

    Example::

        chat_id = chat_id_for("hongming")
        if not chat_id:
            raise RuntimeError("Chat alias 'hongming' not configured in notify.toml")
    """
    return _load_chats().get(alias) or None
