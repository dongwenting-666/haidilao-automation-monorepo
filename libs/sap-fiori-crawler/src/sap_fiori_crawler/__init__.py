"""SAP Fiori crawler (sgpfioriweb.superhi-tech.com).

Per-store login + replay of OData calls behind 盘点报表 (stocktake report).
"""
from importlib.metadata import version

from sap_fiori_crawler.auth import (
    StoreCreds,
    fiori_session,
    load_store_creds,
    login,
)
from sap_fiori_crawler.constants import (
    BASE_URL,
    CREDS_ENV_VAR,
    DEFAULT_CLIENT,
    LAUNCHPAD_URL,
    LOGIN_MAX_ATTEMPTS,
)
from sap_fiori_crawler.errors import (
    FioriError,
    FioriExportError,
    FioriLoginError,
    FioriTimeoutError,
)
from sap_fiori_crawler.entry import (
    DEFAULT_BMID,
    DEFAULT_SUMFLAG,
    ENTRY_OUTPUT_COLUMNS,
    ENTRY_QUERY_ENTITY,
    ENTRY_SERVICE_PATH,
    QUERY_FLAG,
    download_stocktake_entry,
    entry_row_to_output_row,
    fetch_entry_records,
    parse_invh_response,
    write_entry_xlsx,
)
from sap_fiori_crawler.stocktake import (
    ENTITY_SET,
    OUTPUT_COLUMNS,
    SERVICE_PATH,
    api_row_to_output_row,
    build_filter,
    build_period,
    build_url,
    download_stocktake_report,
    fetch_stocktake_records,
    parse_records,
    write_stocktake_xlsx,
)

__version__ = version("sap-fiori-crawler")

__all__ = [
    "BASE_URL",
    "CREDS_ENV_VAR",
    "DEFAULT_BMID",
    "DEFAULT_CLIENT",
    "DEFAULT_SUMFLAG",
    "ENTITY_SET",
    "ENTRY_OUTPUT_COLUMNS",
    "ENTRY_QUERY_ENTITY",
    "ENTRY_SERVICE_PATH",
    "FioriError",
    "FioriExportError",
    "FioriLoginError",
    "FioriTimeoutError",
    "LAUNCHPAD_URL",
    "LOGIN_MAX_ATTEMPTS",
    "OUTPUT_COLUMNS",
    "QUERY_FLAG",
    "SERVICE_PATH",
    "StoreCreds",
    "api_row_to_output_row",
    "build_filter",
    "build_period",
    "build_url",
    "download_stocktake_entry",
    "download_stocktake_report",
    "entry_row_to_output_row",
    "fetch_entry_records",
    "fetch_stocktake_records",
    "fiori_session",
    "load_store_creds",
    "login",
    "parse_invh_response",
    "parse_records",
    "write_entry_xlsx",
    "write_stocktake_xlsx",
]
