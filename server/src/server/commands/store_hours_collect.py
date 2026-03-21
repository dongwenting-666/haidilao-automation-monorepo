
from __future__ import annotations
from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class StoreHoursCollectCommand(BaseCommand):
    name = "store-hours-collect"
    description = "Collect store working-hour data — create monthly sheets, fill turnover/tables, alert unfilled"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "store-hours-collect"

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "store_hours_collect.main",
        ]
        if check_date := params.get("date"):
            args.extend(["--date", str(check_date)])
        return args
