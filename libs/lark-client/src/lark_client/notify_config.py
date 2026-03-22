"""Helpers for resolving named chat aliases from notify.toml.

All projects in this monorepo share ``server/notify.toml``.
The ``[chats]`` section defines human-readable aliases for Lark open_chat_ids::

    [chats]
    hongming    = "oc_..."   # see server/notify.toml for actual IDs
    store_hours = "oc_..."

Per-command sections can carry multiple named chat keys::

    [store-hours-collect]
    chat       = "hongming"     # run-complete card  (used by server notify)
    alert_chat = "store_hours"  # unfilled-store alert

Use ``chat_id_for(alias)`` to resolve a ``[chats]`` alias.
Use ``command_chat_for(command, key)`` to resolve a per-command chat key.

Usage:
    from lark_client.notify_config import chat_id_for, command_chat_for

    chat_id       = chat_id_for("hongming")
    alert_chat_id = command_chat_for("store-hours-collect", "alert_chat")
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
def _load_notify_toml() -> dict:
    """Load and cache the full notify.toml.

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
            return tomllib.load(f)
    except Exception:
        log.exception("Failed to load notify.toml")
        return {}


@lru_cache(maxsize=1)
def _load_chats() -> dict[str, str]:
    """Return the ``[chats]`` table from notify.toml (cached separately for tests)."""
    return _load_notify_toml().get("chats", {})


def chat_id_for(alias: str) -> str | None:
    """Resolve a named chat alias to its Lark open_chat_id.

    Returns the raw open_chat_id string, or None if the alias is not defined.

    Example::

        chat_id = chat_id_for("hongming")
        if not chat_id:
            raise RuntimeError("Chat alias 'hongming' not configured in notify.toml")
    """
    return _load_chats().get(alias) or None


def command_chat_for(command: str, key: str = "chat") -> str | None:
    """Resolve a per-command chat key from notify.toml to a Lark open_chat_id.

    Reads ``key`` from the ``[<command>]`` section, then resolves it as a
    ``[chats]`` alias.  Returns None if either the key or the alias is absent.

    Example::

        # notify.toml:
        #   [store-hours-collect]
        #   chat       = "hongming"
        #   alert_chat = "store_hours"

        run_chat_id   = command_chat_for("store-hours-collect")            # "chat" key
        alert_chat_id = command_chat_for("store-hours-collect", "alert_chat")
    """
    config = _load_notify_toml()
    entry = config.get(command, {})
    alias = entry.get(key)
    if not alias:
        log.debug("notify.toml [%s]: key %r not set", command, key)
        return None
    chat_id = chat_id_for(alias)
    if chat_id is None:
        log.warning("notify.toml [%s]: %r alias %r not found in [chats]", command, key, alias)
    return chat_id
