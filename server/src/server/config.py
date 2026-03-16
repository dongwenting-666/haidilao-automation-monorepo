from pathlib import Path

from pydantic_settings import BaseSettings


def _find_repo_root() -> Path:
    """Walk up from this file to find the monorepo root (contains pyproject.toml
    with workspace config)."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        candidate = parent / "pyproject.toml"
        if candidate.is_file() and "workspace" in candidate.read_text():
            return parent
    # Fallback to depth-based resolution
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    daily_report_cron: str = "0 6 * * *"
    output_dir: Path = REPO_ROOT / "output"

    model_config = {"env_prefix": "SERVER_"}


settings = Settings()
