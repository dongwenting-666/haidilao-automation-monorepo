from pathlib import Path

from pydantic_settings import BaseSettings


def _find_repo_root() -> Path:
    """Walk up from this file to find the monorepo root.

    Identifies the root by looking for a pyproject.toml that contains
    [tool.uv.workspace] (only the workspace root has this).
    """
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        candidate = parent / "pyproject.toml"
        if candidate.is_file() and "[tool.uv.workspace]" in candidate.read_text():
            return parent
    # Fallback to depth-based resolution
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    daily_report_cron: str = "0 6 * * *"
    output_dir: Path = REPO_ROOT / "output"

    # Lark (Feishu) bot — set in .env to enable notifications
    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_notify_chat_id: str = ""   # group chat open_chat_id
    lark_notify_user_id: str = ""   # user open_id (fallback if no chat_id)

    model_config = {"env_prefix": "", "extra": "ignore"}

    @property
    def lark_enabled(self) -> bool:
        """True if Lark credentials are configured."""
        return bool(self.lark_app_id and self.lark_app_secret)

    @property
    def lark_notify_target(self) -> tuple[str | None, str | None]:
        """Return (chat_id, user_id) for notifications. One will be None."""
        if self.lark_notify_chat_id:
            return self.lark_notify_chat_id, None
        if self.lark_notify_user_id:
            return None, self.lark_notify_user_id
        return None, None


settings = Settings(_env_file=REPO_ROOT / ".env", _env_file_encoding="utf-8")
