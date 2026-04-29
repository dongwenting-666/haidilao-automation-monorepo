"""Haidilao POS web crawler (pos.superhi-tech.com)."""

from importlib.metadata import version

from pos_crawler.auth import POSSession
from pos_crawler.constants import BASE_URL, DEFAULT_STORAGE_PATH
from pos_crawler.errors import POSError, POSLoginExpiredError, POSTimeoutError

__version__ = version("pos-crawler")

__all__ = [
    "BASE_URL",
    "DEFAULT_STORAGE_PATH",
    "POSError",
    "POSLoginExpiredError",
    "POSSession",
    "POSTimeoutError",
]
