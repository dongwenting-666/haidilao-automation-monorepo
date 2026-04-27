from __future__ import annotations

from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class CompetitorTakeoutReportCommand(BaseCommand):
    name = "competitor-takeout-report"
    description = "Export the Canada competitor takeout revenue comparison sheet from the latest daily report"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "daily-store-operation-report"

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "daily_store_operation_report.export_competitor_takeout",
        ]
        if date := params.get("date"):
            args.append(str(date))
        if source := params.get("source"):
            args.extend(["--source", str(source)])
        if output_dir := params.get("output_dir"):
            args.extend(["--output-dir", str(output_dir)])
        return args
