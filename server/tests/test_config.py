"""Tests for server.config."""


def test_find_repo_root_finds_workspace_toml():
    from server.config import REPO_ROOT

    toml = REPO_ROOT / "pyproject.toml"
    assert toml.is_file()
    assert "workspace" in toml.read_text()


def test_settings_defaults():
    from server.config import REPO_ROOT, Settings

    s = Settings()
    assert s.server_host == "0.0.0.0"
    assert s.server_port == 8000
    assert s.daily_report_cron == "0 6 * * *"
    assert s.output_dir == REPO_ROOT / "output"


def test_settings_env_override(monkeypatch):
    from server.config import Settings

    # Settings uses env_prefix="" so vars are accessed directly without prefix
    monkeypatch.setenv("SERVER_PORT", "9999")
    monkeypatch.setenv("DAILY_REPORT_CRON", "30 7 * * 1-5")
    s = Settings()
    assert s.server_port == 9999
    assert s.daily_report_cron == "30 7 * * 1-5"
