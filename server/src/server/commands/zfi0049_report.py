from __future__ import annotations

from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class ZFI0049ReportCommand(BaseCommand):
    name = "zfi0049-report"
    description = "Export SAP ZFI0049 raw data and generate Canada PnL workbook"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "zfi0049-report"

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
            "python", "-m", "zfi0049_report.main",
            "--company-code", str(params.get("company_code", "9451")),
            "--fiscal-year", str(params.get("fiscal_year", "")),
            "--posting-period", str(params.get("posting_period", "")),
            "--gl-low", str(params.get("gl_low", "50000000")),
            "--gl-high", str(params.get("gl_high", "69999999")),
            "--max-hits", str(params.get("max_hits", 10_000_000)),
        ]
        return args
