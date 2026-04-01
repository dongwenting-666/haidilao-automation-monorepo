from __future__ import annotations
from pathlib import Path
from typing import Any

from server.commands.base import BaseCommand
from server.config import REPO_ROOT


class F13ClearingCommand(BaseCommand):
    name = "f13-clearing"
    description = "Run F.13 automatic clearing (自动清帐) — clears GL account 22029999 for previous month"

    @property
    def working_dir(self) -> Path:
        return REPO_ROOT / "libs" / "sap-gui"

    def validate(self, params: dict[str, Any]) -> str | None:
        import os
        if os.environ.get("HAIDILAO_SAP_ENABLED") != "1":
            return (
                "F.13/SAP automation is disabled on this machine. "
                "Set HAIDILAO_SAP_ENABLED=1 in .env to enable it."
            )
        return None

    def build_args(self, params: dict[str, Any]) -> list[str]:
        args = [
            "uv", "run",
            "--project", str(self.working_dir),
            "python", str(REPO_ROOT / "libs" / "sap-gui" / "tests" / "e2e_f13.py"),
        ]
        return args
