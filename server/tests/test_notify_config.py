"""Tests for lark_client.notify_config — chat alias resolution."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    from lark_client.notify_config import _load_chats
    _load_chats.cache_clear()
    yield
    _load_chats.cache_clear()


class TestChatIdFor:
    def test_resolves_known_alias(self, monkeypatch):
        from lark_client import notify_config as nc
        monkeypatch.setattr(nc, "_load_chats", lambda: {"test": "oc_123"})
        assert nc.chat_id_for("test") == "oc_123"

    def test_returns_none_for_unknown(self, monkeypatch):
        from lark_client import notify_config as nc
        monkeypatch.setattr(nc, "_load_chats", lambda: {"test": "oc_123"})
        assert nc.chat_id_for("nonexistent") is None

    def test_returns_none_for_empty_string_value(self, monkeypatch):
        from lark_client import notify_config as nc
        monkeypatch.setattr(nc, "_load_chats", lambda: {"test": ""})
        assert nc.chat_id_for("test") is None


class TestFindRepoRoot:
    def test_finds_repo_root(self):
        from lark_client.notify_config import _find_repo_root
        root = _find_repo_root()
        assert (root / "pyproject.toml").exists()
        assert "[tool.uv.workspace]" in (root / "pyproject.toml").read_text()


class TestLoadChats:
    def test_loads_from_real_file(self):
        """Integration test: loads the real server/notify.toml."""
        from lark_client.notify_config import _load_chats
        chats = _load_chats()
        assert "hongming" in chats
        assert chats["hongming"].startswith("oc_")

    def test_missing_file_returns_empty(self, monkeypatch):
        from lark_client import notify_config as nc
        monkeypatch.setattr(nc, "_find_repo_root", lambda: nc.Path("/nonexistent"))
        nc._load_chats.cache_clear()
        assert nc._load_chats() == {}
