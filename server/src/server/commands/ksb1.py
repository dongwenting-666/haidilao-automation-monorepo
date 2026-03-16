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

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", "-m", "ksb1_accounting_check.main",
        ]
        if model := params.get("model"):
            args.extend(["--model", str(model)])
        return args
