"""Shared constants for the POS crawler."""

from pathlib import Path

BASE_URL = "https://pos.superhi-tech.com"

# Default path for Playwright browser storage state (cookies + localStorage).
# Saved after manual login, reused for headless sessions until expiry.
DEFAULT_STORAGE_PATH = Path.home() / ".haidilao" / "pos-storage-state.json"
