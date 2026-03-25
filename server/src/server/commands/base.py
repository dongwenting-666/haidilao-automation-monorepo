
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseCommand(ABC):
    """Base class for all runnable commands."""

    name: str
    description: str

    @abstractmethod
    def build_args(self, params: dict[str, Any]) -> list[str]:
        """Build the full subprocess command list from API parameters."""

    def validate(self, params: dict[str, Any]) -> str | None:
        """Optional pre-run validation. Return an error string to block the run, or None to allow."""
        return None

    @property
    @abstractmethod
    def working_dir(self) -> Path:
        """Project directory for ``uv run --project``."""
