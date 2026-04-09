
from __future__ import annotations
from server.commands.base import BaseCommand
from server.commands.daily_report import DailyReportCommand
from server.commands.f13_clearing import F13ClearingCommand
from server.commands.ksb1 import KSB1Command
from server.commands.store_hours_collect import StoreHoursCollectCommand
from server.commands.travel_budget import TravelBudgetCommand
from server.commands.treasury_loan_watch import TreasuryLoanWatchCommand

_COMMANDS: dict[str, BaseCommand] = {}


def _register(cmd: BaseCommand) -> None:
    _COMMANDS[cmd.name] = cmd


_register(DailyReportCommand())
_register(F13ClearingCommand())
_register(KSB1Command())
_register(TravelBudgetCommand())
_register(TreasuryLoanWatchCommand())
_register(StoreHoursCollectCommand())


def get_command(name: str) -> BaseCommand | None:
    return _COMMANDS.get(name)


def list_commands() -> list[BaseCommand]:
    return list(_COMMANDS.values())
