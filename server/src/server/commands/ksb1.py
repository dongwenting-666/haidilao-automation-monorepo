
from __future__ import annotations
from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class KSB1Command(BaseCommand):
    name = "ksb1"
    description = "Run KSB1 accounting check — exports SAP data and analyses with LLM"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "projects" / "ksb1-accounting-check"

    def validate(self, params: dict[str, Any]) -> str | None:
        """Return an error message if the command should not be run, else None."""
        import os
        if os.environ.get("HAIDILAO_SAP_ENABLED") != "1":
            return (
                "KSB1/SAP automation is disabled on this machine. "
                "Set HAIDILAO_SAP_ENABLED=1 in .env to enable it."
            )
        return None

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "ksb1_accounting_check.main",
        ]
        # Positional month/year args (must come before flags)
        if month := params.get("month"):
            args.append(str(month))
            if year := params.get("year"):
                args.append(str(year))
        if params.get("skip_download"):
            args.append("--skip-download")
        if model := params.get("model"):
            args.extend(["--model", str(model)])
        return args
