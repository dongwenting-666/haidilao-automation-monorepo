"""Quick BI web crawler for Haidilao dashboards."""

from importlib.metadata import version

from qbi_crawler.auth import QBISession
from qbi_crawler.constants import BASE_URL
from qbi_crawler.dashboard import (
    DEFAULT_OUTPUT_SUBDIR,
    REPORT_24H,
    REPORT_DAILY,
    REPORT_TIME_PERIOD,
    download_report,
    export_excel,
    navigate_to_report,
    set_date_range,
)
from qbi_crawler.errors import QBIError, QBILoginError, QBITimeoutError

__version__ = version("qbi-crawler")

__all__ = [
    "BASE_URL",
    "DEFAULT_OUTPUT_SUBDIR",
    "QBIError",
    "QBILoginError",
    "QBISession",
    "QBITimeoutError",
    "REPORT_24H",
    "REPORT_DAILY",
    "REPORT_TIME_PERIOD",
    "download_report",
    "export_excel",
    "navigate_to_report",
    "set_date_range",
]
