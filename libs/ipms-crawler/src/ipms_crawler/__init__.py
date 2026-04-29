"""Haidilao IPMS web crawler (ipms-global.superhi-tech.com)."""

from importlib.metadata import version

from ipms_crawler.auth import IPMSSession
from ipms_crawler.constants import BASE_URL, BOM_URL, DEFAULT_STORAGE_PATH
from ipms_crawler.errors import IPMSError, IPMSExportError, IPMSLoginExpiredError, IPMSTimeoutError

__version__ = version("ipms-crawler")

__all__ = [
    "BASE_URL",
    "BOM_URL",
    "DEFAULT_STORAGE_PATH",
    "IPMSError",
    "IPMSExportError",
    "IPMSLoginExpiredError",
    "IPMSSession",
    "IPMSTimeoutError",
]
