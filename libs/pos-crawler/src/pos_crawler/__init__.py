"""Haidilao POS web crawler (pos.superhi-tech.com)."""

from importlib.metadata import version

from pos_crawler.auth import POSSession
from pos_crawler.constants import BASE_URL, DEFAULT_STORAGE_PATH
from pos_crawler.dish_sales import (
    GROUP_COLLECT_BY_COLUMN,
    GROUP_COLLECT_SUMMARY,
    OUTPUT_COLUMNS,
    REPORT_URL as DISH_SALES_URL,
    api_row_to_output_row,
    download_dish_sales,
)
from pos_crawler.errors import POSError, POSLoginExpiredError, POSTimeoutError

__version__ = version("pos-crawler")

__all__ = [
    "BASE_URL",
    "DEFAULT_STORAGE_PATH",
    "DISH_SALES_URL",
    "GROUP_COLLECT_BY_COLUMN",
    "GROUP_COLLECT_SUMMARY",
    "OUTPUT_COLUMNS",
    "POSError",
    "POSLoginExpiredError",
    "POSSession",
    "POSTimeoutError",
    "api_row_to_output_row",
    "download_dish_sales",
]
