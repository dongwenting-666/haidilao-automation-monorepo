"""盘点录入 (stocktake entry) — fetch the *in-progress* count.

Why this exists
---------------
``stocktake.py`` replays the GET on InvHisSet, which only exposes
*archived* (submitted/posted) stocktake sessions. While a count is
still being entered, those records aren't archived yet and InvHisSet
returns nothing — but the operations team is already entering numbers
into the 盘点录入 Fiori app and the 盘点后下载 button on that page does
export the live counts.

This module replays the same OData call the 盘点录入 app's onDownload
handler relies on. The Fiori SmartTable in ``zui5_inv_entry`` is fed
by a deep-create POST against ``InvHSet`` (a query-by-envelope pattern
where the request body carries the filter and the response embeds the
items in ``InvH_I.results``).

Wire format
-----------
- Endpoint: ``POST /sap/opu/odata/sap/ZGW_INV_ENTRY_SRV/InvHSet``
- Headers: ``X-CSRF-Token`` (fetch via prior GET), ``Content-Type:
  application/json``, ``Accept: application/json``
- Body envelope::

      {
        "ITmpid": "", "IPdtxt": "", "OPdtxt": "",
        "IBmid":  "<dept>",   # "99" for 库管 (warehouse) — matches the
                              # /Main/99/库管/N route
        "IFlag":  "5",        # "5" = 查询 (query mode)
        "ISumflag": "Y",      # any non-"I" value (e.g. "Y","N","O") returns
                              # the in-progress counts; "I" returns the
                              # zeroed initial baseline
        "IUser":  "<store>",  # SAP user code, e.g. "CA8DKG"
        "InvH_I": []          # required — without it the gateway routes
                              # to CREATE_ENTITY (501) instead of
                              # CREATE_DEEP_ENTITY (201)
      }

Field mapping (response → xlsx)
-------------------------------
The InvI items use slightly different field names than InvHisSet, but
the meaning is the same:

    Werks   → 工厂          e.g. "CA08"
    Matnr   → 物料号        e.g. "4509062"
    Matxt   → 名称          e.g. "烧酒（JINRO CHANISUL FRESH，360ML/瓶）"
    Meins   → 单位代码       e.g. "BOT"  (SAP unit code — InvHisSet calls
                                          this Meins too, but rendering-
                                          wise this is the alt code)
    Msetxt  → 单位描述       e.g. "瓶-瓶"  (the bilingual "瓶-瓶")
    Msehi1  → 单位编码       e.g. "BOT"  (same as Meins for most rows;
                                          present on the wire so we keep
                                          it for the manual schema)
    Menge   → 库存数量
    MengePd → 盘点数量      ← the live count
    Status  → 状态 (numeric: "1" = 新建, "2" = 修改, "" = 未盘 etc.)
    Line    → 行号 (zero-padded, e.g. "00010")
    Pici/Zdate/Ztime — empty until the session is posted/archived.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from playwright.sync_api import (
    APIRequestContext,
    BrowserContext,
    Error as PlaywrightError,
)

from sap_fiori_crawler.constants import BASE_URL
from sap_fiori_crawler.errors import FioriExportError, FioriTimeoutError

logger = logging.getLogger(__name__)


ENTRY_SERVICE_PATH = "/sap/opu/odata/sap/ZGW_INV_ENTRY_SRV"
ENTRY_QUERY_ENTITY = "InvHSet"

# Department / org code seen in the production URL "/Main/99/库管/N".
# Other roles (e.g. 部门盘点) use different codes; expose as a parameter.
DEFAULT_BMID = "99"

# IFlag = "5" is the query mode (vs save/post).
QUERY_FLAG = "5"

# Sumflag "I" returns the zero-baseline; anything else returns the live
# in-progress counts. We default to "Y" because that's what the
# launchpad's first inisialData call uses.
DEFAULT_SUMFLAG = "Y"


# Same column layout as ``stocktake.OUTPUT_COLUMNS`` so a downstream
# reader (e.g. ``inventory_check.report._read_fiori_count_by_matnr``)
# works against either source. The entry endpoint has no Pici/Zdate/
# Ztime, so 状态 carries the numeric InvI Status code and 盘点日期 / 时间
# render blank.
ENTRY_OUTPUT_COLUMNS: tuple[str, ...] = (
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


def _to_number(s: Any) -> float | int | str:
    """Coerce SAP numeric strings to float, missing → ''.

    Mirrors ``stocktake._to_number`` so InvI and InvHisSet rows behave
    the same downstream.
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


def entry_row_to_output_row(row: dict[str, Any]) -> list[Any]:
    """Map one InvI record to ``ENTRY_OUTPUT_COLUMNS``.

    Pure (no I/O), unit-testable. Output column order mirrors
    ``stocktake.OUTPUT_COLUMNS`` exactly so the file is interchangeable
    with the InvHisSet-archived workbook.
    """
    return [
        (row.get("Werks") or "").strip(),
        (row.get("Matnr") or "").strip(),
        (row.get("Matxt") or "").strip(),
        # 单位 — InvHisSet uses Meins (the SAP code, e.g. "BOT"); the
        # entry payload puts the same value in Meins (with Msehi1 as
        # a duplicate). Keep that behaviour for column compatibility.
        (row.get("Meins") or row.get("Msehi1") or "").strip(),
        (row.get("Msetxt") or "").strip(),
        _to_number(row.get("Menge")),
        _to_number(row.get("MengePd")),
        # 状态 — the entry path returns a numeric code ("1"/"2"/""); the
        # archive path returns text like "已过账". Keep as-is so the
        # source is obvious to a human reader.
        (row.get("Status") or "").strip(),
        # 盘点日期 / 时间 — archive-only fields. Entry rows leave them
        # blank, matching the manual export's behaviour mid-count.
        (row.get("Zdate") or "").strip(),
        (row.get("Ztime") or "").strip(),
    ]


def parse_invh_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the items array out of the deep-create response.

    Shape::

        {"d": {..., "InvH_I": {"results": [ ... ]}}}

    A few SAP gateways flatten ``"InvH_I"`` to a list directly; we
    accept both.
    """
    d = payload.get("d")
    if not isinstance(d, dict):
        raise FioriExportError(
            f"InvHSet response missing 'd' object — got {type(payload).__name__}"
        )
    nav = d.get("InvH_I")
    if isinstance(nav, dict):
        results = nav.get("results")
        if isinstance(results, list):
            return results
    if isinstance(nav, list):
        return nav
    raise FioriExportError(
        f"InvHSet response missing 'd.InvH_I.results' — keys: {list(d.keys())[:10]}"
    )


def _fetch_csrf_token(
    request: APIRequestContext, *, base: str = BASE_URL, timeout_ms: int = 30_000
) -> str:
    """Fetch an X-CSRF-Token from the OData service root.

    SAP gateways require a non-GET (POST/PUT/DELETE) to carry a token
    that was previously issued via a GET with ``X-CSRF-Token: Fetch``.
    We use the service root as the cheap GET target.
    """
    url = f"{base}{ENTRY_SERVICE_PATH}/"
    try:
        resp = request.get(
            url,
            headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"},
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        raise FioriTimeoutError(f"CSRF fetch GET {url} failed: {exc}") from exc
    if resp.status >= 400:
        raise FioriExportError(
            f"CSRF fetch returned status {resp.status}: {resp.text()[:300]}"
        )
    token = resp.headers.get("x-csrf-token")
    if not token:
        raise FioriExportError(
            "CSRF fetch response did not include x-csrf-token header"
        )
    return token


def fetch_entry_records(
    request: APIRequestContext,
    *,
    user: str,
    bmid: str = DEFAULT_BMID,
    sumflag: str = DEFAULT_SUMFLAG,
    timeout_ms: int = 60_000,
) -> list[dict[str, Any]]:
    """POST the deep-create query envelope and return InvI rows.

    ``request`` is a Playwright ``APIRequestContext`` carrying Fiori
    session cookies (typically ``context.request``).

    By default ``sumflag="Y"`` returns the live in-progress count. Pass
    ``sumflag="I"`` to get the zero-baseline (the input to the count).
    """
    if "'" in user:
        raise ValueError(f"user contains a quote: {user!r}")
    csrf = _fetch_csrf_token(request, timeout_ms=timeout_ms)
    body = {
        "ITmpid": "",
        "IPdtxt": "",
        "OPdtxt": "",
        "IBmid": bmid,
        "IFlag": QUERY_FLAG,
        "ISumflag": sumflag,
        "IUser": user,
        "InvH_I": [],
    }
    url = f"{BASE_URL}{ENTRY_SERVICE_PATH}/{ENTRY_QUERY_ENTITY}"
    logger.info("POST %s sumflag=%s user=%s bmid=%s", url, sumflag, user, bmid)
    try:
        resp = request.post(
            url,
            headers={
                "X-CSRF-Token": csrf,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        raise FioriTimeoutError(f"POST {url} failed: {exc}") from exc

    # The gateway returns 201 Created for the deep-create envelope even
    # though we're really doing a query.
    if resp.status not in (200, 201):
        body_txt = ""
        try:
            body_txt = resp.text()
        except PlaywrightError:
            pass
        raise FioriExportError(
            f"InvHSet POST returned status {resp.status}: {body_txt[:400]}"
        )

    try:
        payload = json.loads(resp.body())
    except (json.JSONDecodeError, PlaywrightError) as exc:
        raise FioriExportError(f"InvHSet POST response was not JSON: {exc}") from exc
    return parse_invh_response(payload)


def _default_filename(period: str, store_key: str) -> str:
    """File name for the live-count download.

    Uses an ``-entry-`` infix so it doesn't collide with the
    InvHisSet-based ``SGP-{store}-盘点-{period}.xlsx``.

    >>> _default_filename("202604", "CA8DKG")
    'SGP-CA8DKG-盘点录入-202604.xlsx'
    """
    return f"SGP-{store_key}-盘点录入-{period}.xlsx"


def write_entry_xlsx(
    rows: list[dict[str, Any]],
    out_path: Path,
    *,
    sheet_name: str = "盘点录入",
) -> Path:
    """Write InvI rows to xlsx using ``ENTRY_OUTPUT_COLUMNS``.

    Returns the path written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.append(list(ENTRY_OUTPUT_COLUMNS))
    for row in rows:
        ws.append(entry_row_to_output_row(row))
    wb.save(str(out_path))
    logger.info("wrote %d rows → %s", len(rows), out_path)
    return out_path


def download_stocktake_entry(
    context: BrowserContext,
    *,
    user: str,
    period: str,
    bmid: str = DEFAULT_BMID,
    sumflag: str = DEFAULT_SUMFLAG,
    out_dir: Path | str = Path.cwd(),
    file_name: str | None = None,
) -> Path:
    """Download the live (in-progress) stocktake entry as xlsx.

    Args:
        context: Playwright ``BrowserContext`` (already logged in).
        user: SAP user / store key, e.g. ``CA8DKG``.
        period: Period stamp for the file name (YYYYMM). The OData
            call itself doesn't take a period — the live entry is
            inherently for the current open window — but we tag the
            output with it so files are distinguishable.
        bmid: Department code; default ``"99"`` matches 库管 in the
            production URL.
        sumflag: ``"Y"`` (default) returns the in-progress count;
            ``"I"`` returns the zero-baseline.
        out_dir: Where to drop the xlsx.
        file_name: Override default file name.

    Returns the path of the saved xlsx.
    """
    rows = fetch_entry_records(
        context.request, user=user, bmid=bmid, sumflag=sumflag,
    )
    out_dir = Path(out_dir)
    name = file_name or _default_filename(period, user)
    return write_entry_xlsx(rows, out_dir / name)
