from server.commands.base import BaseCommand
from server.commands.daily_report import DailyReportCommand
from server.commands.ksb1 import KSB1Command

_COMMANDS: dict[str, BaseCommand] = {}


def _register(cmd: BaseCommand) -> None:
    _COMMANDS[cmd.name] = cmd


_register(DailyReportCommand())
_register(KSB1Command())


def get_command(name: str) -> BaseCommand | None:
    return _COMMANDS.get(name)


def list_commands() -> list[BaseCommand]:
    return list(_COMMANDS.values())
