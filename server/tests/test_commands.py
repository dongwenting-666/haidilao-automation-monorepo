"""Tests for server.commands registry and concrete command classes."""

from server.commands import get_command, list_commands
from server.commands.daily_report import DailyReportCommand
from server.commands.ksb1 import KSB1Command
from server.config import REPO_ROOT


# --- Registry ---


def test_list_commands_returns_both():
    cmds = list_commands()
    names = {c.name for c in cmds}
    assert names == {"daily-report", "ksb1"}


def test_get_command_found():
    cmd = get_command("ksb1")
    assert cmd is not None
    assert isinstance(cmd, KSB1Command)


def test_get_command_not_found():
    assert get_command("nonexistent") is None


# --- DailyReportCommand ---


class TestDailyReportCommand:
    cmd = DailyReportCommand()

    def test_working_dir(self):
        assert self.cmd.working_dir == REPO_ROOT / "projects" / "daily-store-operation-report"

    def test_build_args_no_params(self):
        args = self.cmd.build_args({})
        assert args == [
            "uv", "run",
            "--project", str(self.cmd.working_dir),
            "python", "-m", "daily_store_operation_report.main",
        ]

    def test_build_args_date(self):
        args = self.cmd.build_args({"date": "2026-03-01"})
        assert args[-1] == "2026-03-01"

    def test_build_args_skip_download(self):
        args = self.cmd.build_args({"skip_download": True})
        assert "--skip-download" in args

    def test_build_args_data_dir(self):
        args = self.cmd.build_args({"data_dir": "/tmp/data"})
        idx = args.index("--data-dir")
        assert args[idx + 1] == "/tmp/data"

    def test_build_args_all_combined(self):
        args = self.cmd.build_args({
            "date": "2026-01-15",
            "skip_download": True,
            "data_dir": "/out",
        })
        assert "2026-01-15" in args
        assert "--skip-download" in args
        assert "--data-dir" in args
        assert "/out" in args


# --- KSB1Command ---


class TestKSB1Command:
    cmd = KSB1Command()

    def test_working_dir(self):
        assert self.cmd.working_dir == REPO_ROOT / "projects" / "ksb1-accounting-check"

    def test_build_args_no_params(self):
        args = self.cmd.build_args({})
        assert args == [
            "uv", "run",
            "--project", str(self.cmd.working_dir),
            "python", "-m", "ksb1_accounting_check.main",
        ]

    def test_build_args_model(self):
        args = self.cmd.build_args({"model": "qwen3:8b"})
        assert args[-2:] == ["--model", "qwen3:8b"]
