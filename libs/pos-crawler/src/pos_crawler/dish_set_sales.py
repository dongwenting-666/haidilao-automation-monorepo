"""菜品套餐报表 (set-meal sales breakdown) export from POS Hongfutai.

Why this exists
---------------
The inventory-check 计算 sheet's W (套餐拼盘用量) formula reads from a
``BI套餐`` sheet to attribute set-meal sales to their constituent dishes.
The manual workbook had this sheet hand-curated (28 cols including BI/finance
fields). POS exposes ``/repDishSale/listDishSetSale`` (菜品套餐报表) which
provides the dish-level breakdown of set-meal sales — enough for the 计算
sheet's W formula, which only needs:

    BI套餐!K (菜品编码)  + BI套餐!T (应收数量)

We replay the same paginated list API used by ``listDishPotSale``
(same auth model, same MD5 sig algorithm — see :mod:`dish_sales`) and
write a normalised xlsx that the inventory-check pipeline ingests.

Output schema (sheet ``红火台套餐汇总``)
--------------------------------------
Mirrors the manual ``BI套餐`` layout to keep the calc-sheet formula
``=SUMIF(BI套餐!K:K, F2, BI套餐!T:T)*N4`` working without modification:

    A 月份 | B 国家 | C 门店名称 | D 销售模式 | E 大类名称 | F 小类名称 |
    G 套餐编码 | H 套餐名称 | I 套餐规格 | J 套餐单价 |
    K 菜品编码 | L 菜品名称 | M 菜品规格名称 | N 菜品单价 | O 菜品单位 |
    P 出品数量 | Q 出品金额 | R 退菜数量 | S 退菜金额 |
    T 应收数量 | U 应收金额 | V 套餐折扣 | W 实收金额 |
    X 销售产品净收入 | Y 税额 | Z 净额

The K and T cols are the only ones the calc sheet reads. Cells we can't
populate from POS (e.g., 销售产品净收入, 税额, 净额 — those are BI/finance
post-processing fields) are left blank.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from playwright.sync_api import Page

from pos_crawler.dish_sales import (
    GROUP_COLLECT_BY_COLUMN, GROUP_COLLECT_SUMMARY,
    _extract_creds, _is_iso_date, _sign_params, _switch_store,
)
from pos_crawler.errors import POSError

logger = logging.getLogger(__name__)

# POS only registers a single SPA route for sales reports; the listDishPotSale
# and listDishSetSale endpoints both serve from the same page (the `tabs`
# inside the page select between them client-side). Navigating to a route
# that doesn't exist (the obvious "saleDishSetReport") leaves the page in a
# broken state where the header-dropdown vanishes — verified by an e2e run
# where CA01 succeeded but CA02 onward failed because the dropdown locator
# timed out. Reuse the dish-sales report URL so the page state stays valid.
REPORT_URL = "https://pos.superhi-tech.com/#/shopMgr/saleDishPotReport"
LIST_API = "https://pos.superhi-tech.com:8032/repDishSale/listDishSetSale"

# 28-col layout matching the manual BI套餐 sheet. Values not present in
# the POS response are left None (e.g. 销售产品净收入 / 税额 / 净额 are
# BI-platform fields, not POS).
OUTPUT_COLUMNS: tuple[str, ...] = (
    "月份", "国家", "门店名称", "销售模式",
    "大类名称", "小类名称", "套餐编码", "套餐名称",
    "套餐规格", "套餐单价",
    "菜品编码", "菜品名称", "菜品规格名称", "菜品单价", "菜品单位",
    "出品数量", "出品金额", "退菜数量", "退菜金额",
    "应收数量", "应收金额", "套餐折扣", "实收金额",
    "销售产品净收入", "税额", "净额",
)


# Defensive field-name mapping: POS bundle minification varies across
# builds, and the listDishSetSale endpoint hasn't been independently
# probed yet. Each output col tries the most likely API field names in
# order; first non-None wins. Keys correspond to OUTPUT_COLUMNS positions.
#
# After the first live run, inspect the produced xlsx + raw API response
# and tighten this mapping if any of the K/T-bound cols come back blank
# (those are the only ones the calc sheet's W formula reads).
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "月份": ("month", "yearMonth", "billMonth"),
    "国家": ("countryName", "country", "areaCountryName"),
    "门店名称": ("shopName",),
    "销售模式": ("modelName", "saleModelName", "salesModelName"),
    "大类名称": ("bigDishTypeName", "comboTypeName"),
    "小类名称": ("smallDishTypeName", "comboSubTypeName"),
    "套餐编码": ("comboCode", "setCode", "comboDishCode"),
    "套餐名称": ("comboName", "setName", "comboDishName"),
    "套餐规格": ("comboStandardName", "setStandardName"),
    "套餐单价": ("comboPrice", "setPrice", "comboDishPrice"),
    "菜品编码": ("dishCode",),
    "菜品名称": ("dishName",),
    "菜品规格名称": ("standardName", "dishStandardName"),
    "菜品单价": ("dishPrice",),
    "菜品单位": ("unit",),
    "出品数量": ("producedNumber",),
    "出品金额": ("totalMoney", "producedMoney"),
    "退菜数量": ("retreatNumber",),
    "退菜金额": ("retreatMoney",),
    "应收数量": ("payNumber", "payQuantity", "applyNumber", "receivableNumber"),
    "应收金额": ("payMoney", "receivableMoney"),
    "套餐折扣": ("comboDiscount", "setDiscount"),
    "实收金额": ("realMoney", "actualMoney", "netConsumption"),
    # BI/finance fields — typically absent from POS; tried but expected to
    # come back None.
    "销售产品净收入": ("saleNetIncome", "netIncome"),
    "税额": ("taxMoney", "taxAmount"),
    "净额": ("netAmount", "netMoney"),
}


def api_row_to_output_row(row: dict[str, Any], *, period: str | None = None,
                          country: str = "加拿大") -> list[Any]:
    """Map one /repDishSale/listDishSetSale row to the 28-col output layout.

    period (e.g. ``"202604"``) is supplied by the caller because the API
    response usually omits it for date-range queries. country defaults
    to ``加拿大`` since the inventory-check use case is CA-only.
    """
    out: list[Any] = []
    for col in OUTPUT_COLUMNS:
        if col == "月份":
            out.append(period)
            continue
        if col == "国家":
            v = row.get("countryName") or row.get("country") or country
            out.append(v)
            continue
        candidates = _FIELD_CANDIDATES.get(col, ())
        v = None
        for k in candidates:
            if k in row and row[k] is not None:
                v = row[k]
                break
        out.append(v)
    return out


def _navigate_and_fetch_via_api(
    page: Page,
    *,
    start_date: str,
    end_date: str,
    group_collect: int,
    page_size: int = 500,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """Replay listDishSetSale paginated. Same auth dance as listDishPotSale."""
    page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_000)

    creds_blob = page.evaluate("""
        () => {
            const out = {localStorage: {}, sessionStorage: {}};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out.localStorage[k] = localStorage.getItem(k);
            }
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                out.sessionStorage[k] = sessionStorage.getItem(k);
            }
            return out;
        }
    """)
    creds = _extract_creds(creds_blob)
    if not creds:
        raise POSError(
            "Could not find shopId/userName/userId in localStorage — "
            "POS session may be expired or the report URL didn't mount."
        )
    logger.info(
        "Set-sale credentials: shopId=%s userName=%s",
        creds["shopId"], creds["userName"],
    )

    list_path = urllib.parse.urlparse(LIST_API).path
    rows: list[dict[str, Any]] = []
    page_num = 1
    while page_num <= max_pages:
        signed = {
            "groupCollect": str(group_collect),
            "date": f"{start_date},{end_date}",
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "shopId": creds["shopId"],
            "userName": creds["userName"],
            "userId": creds["userId"],
        }
        signed["sig"] = _sign_params(list_path, signed)
        full_url = LIST_API + "?" + urllib.parse.urlencode(signed)
        result = page.evaluate(
            """
            async ({url, token}) => {
                try {
                    const r = await fetch(url, {
                        credentials: 'include',
                        headers: {'Token': token, 'timestamp': String(Date.now())},
                    });
                    let body;
                    try { body = await r.json(); }
                    catch (e) { body = {result: r.status, message: 'non-json'}; }
                    return {status: r.status, body};
                } catch (e) {
                    return {status: -1, body: {result: -1, message: 'fetch threw: ' + (e && e.message)}};
                }
            }
            """,
            {"url": full_url, "token": creds["Token"]},
        )
        body = result.get("body") if isinstance(result, dict) else None
        if not body or body.get("result") != 200:
            raise POSError(
                f"set-sale API non-200 on page {page_num}: "
                f"http_status={result.get('status')!r} body={str(body)[:400]!r}"
            )
        data = body.get("data") or {}
        page_rows = data.get("list") or []
        rows.extend(page_rows)
        total_pages = data.get("pages", 1)
        logger.info(
            "  set-sale page %d/%d: +%d rows (running total=%d / %d)",
            page_num, total_pages, len(page_rows), len(rows),
            data.get("total", 0),
        )
        if page_num == 1 and page_rows:
            # First-row schema dump — useful for tightening _FIELD_CANDIDATES
            # if the defaults miss anything. Logged at INFO so it's visible
            # in the all_stores run output.
            logger.info("  set-sale first-row fields: %s",
                        sorted(page_rows[0].keys())[:30])
        if page_num >= total_pages or not page_rows:
            break
        page_num += 1
    return rows


def _write_xlsx(rows: list[dict[str, Any]], output_path: Path,
                *, period: str, country: str = "加拿大") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "红火台套餐汇总"
    ws.append(list(OUTPUT_COLUMNS))
    for row in rows:
        ws.append(api_row_to_output_row(row, period=period, country=country))
    wb.save(output_path)
    logger.info("Wrote %d set-sale rows to %s", len(rows), output_path)
    return output_path


def download_dish_set_sales(
    page: Page,
    *,
    start_date: str,
    end_date: str,
    store_name: str,
    output_dir: Path,
    group_collect: int = GROUP_COLLECT_SUMMARY,
    output_filename: str | None = None,
) -> Path:
    """Drive POS 菜品套餐报表 and write a single xlsx.

    Mirrors :func:`pos_crawler.dish_sales.download_dish_sales` for the
    set-meal endpoint. Skip if the page lacks the dropdown selector — the
    return value is the path to the (possibly 0-row) xlsx.
    """
    if not _is_iso_date(start_date) or not _is_iso_date(end_date):
        raise POSError(
            f"Dates must be YYYY-MM-DD; got start={start_date!r} end={end_date!r}"
        )
    if start_date > end_date:
        raise POSError(f"start_date > end_date: {start_date} > {end_date}")

    logger.info(
        "Downloading 菜品套餐报表 — store=%s dates=%s→%s",
        store_name, start_date, end_date,
    )

    page.wait_for_selector(".header-dropdown", state="visible", timeout=30_000)
    _switch_store(page, store_name)

    rows = _navigate_and_fetch_via_api(
        page, start_date=start_date, end_date=end_date,
        group_collect=group_collect,
    )

    period = start_date[:4] + start_date[5:7]
    if output_filename is None:
        output_filename = (
            f"{store_name}-菜品套餐汇总-"
            f"{start_date.replace('-', '')}-{end_date.replace('-', '')}.xlsx"
        )
    return _write_xlsx(rows, Path(output_dir) / output_filename, period=period)
