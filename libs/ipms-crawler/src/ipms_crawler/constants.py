"""Shared constants for the IPMS crawler."""

from pathlib import Path

BASE_URL = "https://ipms-global.superhi-tech.com"
LOGIN_URL = f"{BASE_URL}/login"
BOM_URL = f"{BASE_URL}/approval/bomMgt/overseasBomList"

# Identity to switch to after login — required for BOM menu access.
TARGET_ROLE = "00 业务分析岗"

# Default browser storage state — saved after manual QR login,
# reused for headless sessions until expiry.
DEFAULT_STORAGE_PATH = Path.home() / ".haidilao" / "ipms-storage-state.json"

# Default download output dir.
DEFAULT_OUTPUT_DIR = Path("output/ipms")
