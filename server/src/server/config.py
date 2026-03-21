
from __future__ import annotations
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

    # Database — optional; DB features degrade gracefully when not set.
    database_url: str = ""

    # Lark (Feishu) bot credentials — set in .env to enable notifications.
    # Notification targets are configured per-command in server/notify.toml.
    lark_app_id: str = ""
    lark_app_secret: str = ""

    # Admin OAuth / session
    admin_whitelist: str = ""        # comma-separated Lark open_ids allowed in admin
    session_secret: str = ""         # HMAC key for signing session cookies
    super_admin_open_ids: str = ""   # comma-separated Lark open_ids with super-admin access
    lark_oauth_redirect_uri: str = "https://haidilao.wanghongming.xyz/admin/oauth/callback"
    cookie_secure: str = "true"      # set to "false" for local HTTP dev

    # GitHub webhook
    github_webhook_secret: str = ""

    # Run guard — required to trigger automation runs via HTTP.
    # Internal scheduler calls create_run() directly and bypasses this.
    # Set to a random secret; any external caller must pass X-Run-Token header.
    run_token: str = ""

    # MinIO file storage
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "haidilao"
    minio_root_password: str = "haidilao_minio_dev"
    minio_bucket: str = "tools-uploads"
    minio_secure: str = "false"

    model_config = {"env_prefix": "", "extra": "ignore"}

    @property
    def lark_enabled(self) -> bool:
        """True if Lark credentials are configured."""
        return bool(self.lark_app_id and self.lark_app_secret)

    @property
    def cookie_secure_bool(self) -> bool:
        return self.cookie_secure.lower() not in ("false", "0", "no")

    @property
    def minio_secure_bool(self) -> bool:
        return self.minio_secure.lower() in ("true", "1", "yes")


settings = Settings(_env_file=REPO_ROOT / ".env", _env_file_encoding="utf-8")
