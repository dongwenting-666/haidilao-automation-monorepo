from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class TreasuryLoanWatchCommand(BaseCommand):
    name = "treasury-loan-watch"
    description = "Check TREASURY loan maturities and notify via Lark"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "treasury-loan-watch"

    def build_args(self, params: dict[str, Any]) -> list[str]:
        return [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "treasury_loan_watch.main",
        ]
