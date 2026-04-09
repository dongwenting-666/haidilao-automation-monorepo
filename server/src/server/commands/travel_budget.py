
from __future__ import annotations
from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class TravelBudgetCommand(BaseCommand):
    name = "travel-expense-budget"
    description = "Travel expense budget report — 差旅费预算明细"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "travel-expense-budget"

    def validate(self, params: dict[str, Any]) -> str | None:
        import os
        if os.environ.get("HAIDILAO_SAP_ENABLED") != "1":
            return (
                "SAP automation is disabled on this machine. "
                "Set HAIDILAO_SAP_ENABLED=1 in .env to enable it."
            )
        return None

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "travel_expense_budget.main",
        ]
        # Positional: report_month year
        if month := params.get("report_month"):
            args.append(str(month))
            if year := params.get("year"):
                args.append(str(year))
        if params.get("skip_download"):
            args.append("--skip-download")
        return args
