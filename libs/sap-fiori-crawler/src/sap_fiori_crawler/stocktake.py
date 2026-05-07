"""盘点报表 (stocktake report) export from SAP Fiori.

Why this exists
---------------
The Fiori 盘点报表 app has no built-in export button — only a settings
gear and a fullscreen toggle on the result table. So we replay the same
OData GET that the SmartTable issues when 执行 is clicked, and assemble
our own xlsx from the JSON payload.

Replay pattern
--------------
After login we have a Playwright ``BrowserContext`` carrying the auth
cookies. We use ``context.request.get(...)`` to call the OData endpoint
directly (no UI driving, no $batch envelope — single GET with $format=json):

    /sap/opu/odata/sap/ZGW_INV_QUERY_SRV/InvHisSet
        ?$filter=ILfper eq '<YYYYMM>' and IUser eq '<storeKey>'
        &$format=json

Field mapping (from a real 200 response, 435 rows for CA8DKG 202603)
--------------------------------------------------------------------

    Matnr   → 物料号        e.g. "1000049"
    Matxt   → 名称          e.g. "金标生抽（海天，4.9L*2桶/件）"
    Meins   → 单位          e.g. "L"
    Msetxt  → 单位描述       e.g. "升-公升"
    Menge   → 库存数量       e.g. "200.900"
    MengePd → 盘点数量       e.g. "63.700"      ← the key column
    Pici    → 状态          e.g. "已过账"
    Zdate   → 盘点日期       e.g. "20260301"
    Ztime   → 时间          e.g. "192948"
    Werks   → 工厂          e.g. "CA08"

We surface 工厂 (Werks) as an extra column so downstream consumers can
identify the store without parsing the user code.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from openpyxl import Workbook
from playwright.sync_api import (
    APIRequestContext,
    BrowserContext,
    Error as PlaywrightError,
)

from sap_fiori_crawler.constants import BASE_URL
from sap_fiori_crawler.errors import FioriExportError, FioriTimeoutError

logger = logging.getLogger(__name__)

# Final xlsx columns — 9 visible columns from the Fiori UI plus 工厂 for
# downstream attribution.
OUTPUT_COLUMNS: tuple[str, ...] = (
    "工厂",
    "物料号",
    "名称",
    "单位",
    "单位描述",
    "库存数量",
    "盘点数量",
    "状态",
    "盘点日期",
    "时间",
)

ENTITY_SET = "InvHisSet"
SERVICE_PATH = "/sap/opu/odata/sap/ZGW_INV_QUERY_SRV"


def build_period(year: int, month: int) -> str:
    """SAP period string (YYYYMM, zero-padded month).

    >>> build_period(2026, 3)
    '202603'
    >>> build_period(2026, 12)
    '202612'
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    if year < 1900 or year > 9999:
        raise ValueError(f"year out of range: {year}")
    return f"{year:04d}{month:02d}"


def build_filter(period: str, user: str) -> str:
    """OData $filter fragment for the InvHisSet query.

    The OData service requires both ILfper (period) and IUser (store key).

    >>> build_filter("202603", "CA8DKG")
    "ILfper eq '202603' and IUser eq 'CA8DKG'"
    """
    if "'" in user:
        raise ValueError(f"user contains a quote: {user!r}")
    return f"ILfper eq '{period}' and IUser eq '{user}'"


def build_url(period: str, user: str, *, base: str = BASE_URL) -> str:
    """Full OData URL with filter + $format=json.

    >>> u = build_url("202603", "CA8DKG")
    >>> "InvHisSet" in u and "ILfper" in u and "format=json" in u
    True
    """
    flt = quote(build_filter(period, user))
    return f"{base}{SERVICE_PATH}/{ENTITY_SET}?$filter={flt}&$format=json"


def _to_number(s: Any) -> float | int | str:
    """Coerce SAP numeric strings ('200.900') to float, missing → ''.

    Integer-valued floats are returned as int so the xlsx renders without
    a trailing '.0'. ``None`` collapses to '' so missing fields produce
    blank cells, not literal None.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        return s
    s = s.strip()
    if s == "":
        return ""
    try:
        v = float(s)
    except ValueError:
        return s
    return int(v) if v == int(v) else v


def api_row_to_output_row(row: dict[str, Any]) -> list[Any]:
    """Map one InvHisSet record to the OUTPUT_COLUMNS layout.

    Pure (no I/O), unit-testable.
    """
    return [
        (row.get("Werks") or "").strip(),
        (row.get("Matnr") or "").strip(),
        (row.get("Matxt") or "").strip(),
        (row.get("Meins") or "").strip(),
        (row.get("Msetxt") or "").strip(),
        _to_number(row.get("Menge")),
        _to_number(row.get("MengePd")),
        (row.get("Pici") or "").strip(),
        (row.get("Zdate") or "").strip(),
        (row.get("Ztime") or "").strip(),
    ]


def parse_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the rows array out of an OData v2 JSON payload.

    The wrapper shape is ``{"d": {"results": [...]}}``. A few SAP gateways
    flatten that to ``{"d": [...]}``; we accept both.
    """
    d = payload.get("d")
    if isinstance(d, dict):
        results = d.get("results")
        if isinstance(results, list):
            return results
    if isinstance(d, list):
        return d
    raise FioriExportError(
        "OData response missing 'd.results' array — got: "
        f"{type(payload).__name__} with keys {list(payload.keys())[:5]}"
    )


def _default_filename(year: int, month: int, store_key: str) -> str:
    """Default xlsx file name, format SGP-{store}-盘点-{YYYYMM}.xlsx.

    >>> _default_filename(2026, 3, "CA8DKG")
    'SGP-CA8DKG-盘点-202603.xlsx'
    """
    return f"SGP-{store_key}-盘点-{build_period(year, month)}.xlsx"


def write_stocktake_xlsx(
    rows: list[dict[str, Any]],
    out_path: Path,
    *,
    sheet_name: str = "盘点报表",
) -> Path:
    """Write OData rows to xlsx using OUTPUT_COLUMNS.

    Returns the path written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.append(list(OUTPUT_COLUMNS))
    for row in rows:
        ws.append(api_row_to_output_row(row))
    wb.save(str(out_path))
    logger.info("wrote %d rows → %s", len(rows), out_path)
    return out_path


def fetch_stocktake_records(
    request: APIRequestContext,
    *,
    year: int,
    month: int,
    user: str,
    timeout_ms: int = 60_000,
) -> list[dict[str, Any]]:
    """GET /InvHisSet?$filter=… and return parsed records.

    ``request`` is a Playwright ``APIRequestContext`` carrying the
    Fiori session cookies (typically ``context.request``).
    """
    period = build_period(year, month)
    url = build_url(period, user)
    logger.info("GET %s", url)
    try:
        resp = request.get(
            url,
            headers={"Accept": "application/json"},
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        raise FioriTimeoutError(f"GET {url} failed: {exc}") from exc

    if resp.status != 200:
        body = ""
        try:
            body = resp.text()
        except PlaywrightError:
            pass
        raise FioriExportError(
            f"InvHisSet returned status {resp.status}: {body[:300]}"
        )

    try:
        payload = json.loads(resp.body())
    except (json.JSONDecodeError, PlaywrightError) as exc:
        raise FioriExportError(f"InvHisSet response was not JSON: {exc}") from exc
    return parse_records(payload)


def download_stocktake_report(
    context: BrowserContext,
    *,
    year: int,
    month: int,
    user: str,
    out_dir: Path | str = Path.cwd(),
    file_name: str | None = None,
) -> Path:
    """Download and persist a 盘点报表 for ``user`` for the given period.

    Args:
        context: Playwright ``BrowserContext`` (already logged in).
        year: Calendar year, e.g. 2026.
        month: 1-12.
        user: SAP user / store key, e.g. ``CA8DKG``.
        out_dir: Where to drop the xlsx.
        file_name: Override default file name.

    Returns the path of the saved xlsx.
    """
    rows = fetch_stocktake_records(
        context.request, year=year, month=month, user=user
    )
    out_dir = Path(out_dir)
    name = file_name or _default_filename(year, month, user)
    return write_stocktake_xlsx(rows, out_dir / name)
