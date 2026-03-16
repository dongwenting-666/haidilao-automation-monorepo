from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class DailyReportCommand(BaseCommand):
    name = "daily-report"
    description = "Download QBI data and generate the daily store operation report"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "daily-store-operation-report"

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "daily_store_operation_report.main",
        ]
        if date := params.get("date"):
            args.append(str(date))
        if params.get("skip_download"):
            args.append("--skip-download")
        if data_dir := params.get("data_dir"):
            args.extend(["--data-dir", str(data_dir)])
        return args
