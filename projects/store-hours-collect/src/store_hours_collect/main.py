"""Store working-hour data collection.

Daily at 6:30 AM Vancouver time:
1. Check if a monthly spreadsheet exists for the current month in the target folder.
   If not, copy the template to create one.
2. Fill in 翻台率 (column D) and 总桌数 (column E) from daily store report data.
3. Check which blue columns (F–K: staffing data) are still empty for past dates.
   Report unfilled stores to the Lark chat group.

Template: https://haidilao.feishu.cn/sheets/SbTns7kTxhxn5TtLMyccOrqRnqe
Folder:   https://haidilao.feishu.cn/drive/folder/AVt8fGZLHl5PzJd2gw3cNa10ntd

Environment variables:
    LARK_APP_ID / LARK_APP_SECRET   Feishu bot credentials
    HOURS_NOTIFY_CHAT_ID            Lark group chat for notifications
    HOURS_TEMPLATE_TOKEN            Template spreadsheet token (default provided)
    HOURS_FOLDER_TOKEN              Target folder token (default provided)
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import sys
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

TEMPLATE_TOKEN = "SbTns7kTxhxn5TtLMyccOrqRnqe"
FOLDER_TOKEN   = "AVt8fGZLHl5PzJd2gw3cNa10ntd"

STORES = [
    "加拿大一店", "加拿大二店", "加拿大三店", "加拿大四店",
    "加拿大五店", "加拿大六店", "加拿大七店", "加拿大八店",
]

# Template sheet IDs per store (from the template spreadsheet)
STORE_SHEET_IDS = {
    "加拿大一店": "0IXaeb",
    "加拿大二店": "1rrErh",
    "加拿大三店": "2BEubp",
    "加拿大四店": "3DgyiA",
    "加拿大五店": "4aoGEI",
    "加拿大六店": "5MYjYy",
    "加拿大七店": "6OsmBn",
    "加拿大八店": "58PdOV",
}

# Layout: Row 4-5 = headers, Row 6 = day 1 of month
_HEADER_ROWS = 5    # rows before data starts
_COL_DATE = "B"     # date column (Excel serial)
_COL_WEEKDAY = "C"  # weekday column
_COL_TURNOVER = "D" # 翻台率 — we fill this
_COL_TABLES = "E"   # 总桌数 — we fill this
# Blue columns (store clerks must fill): F, G, H, I, J, K
_BLUE_COLS = ["F", "G", "H", "I", "J", "K"]

_LARK_BASE = "https://open.feishu.cn/open-apis"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _excel_serial(d: date) -> int:
    """Convert a Python date to an Excel serial number."""
    return (d - date(1900, 1, 1)).days + 2


def _weekday_cn(d: date) -> str:
    """Return Chinese weekday name for a date."""
    names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return names[d.weekday()]


def _month_file_name(year: int, month: int) -> str:
    return f"加拿大门店用工数据跟踪-{year}{month:02d}"


def _api(token: str, method: str, path: str, **kwargs) -> dict:
    """Call a Lark API endpoint, raise on error."""
    resp = getattr(httpx, method)(
        f"{_LARK_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        **kwargs,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Lark API error: {data.get('code')} {data.get('msg')}")
    return data


# ── Find or create monthly spreadsheet ────────────────────────────────────────

def find_monthly_sheet(token: str, folder_token: str, year: int, month: int) -> str | None:
    """Find an existing monthly spreadsheet in the folder. Returns token or None."""
    target_name = _month_file_name(year, month)
    resp = httpx.get(
        f"{_LARK_BASE}/drive/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"folder_token": folder_token, "page_size": 50},
        timeout=15,
    )
    resp.raise_for_status()
    files = resp.json().get("data", {}).get("files", [])
    for f in files:
        if target_name in f.get("name", ""):
            logger.info("Found existing sheet: %s (token=%s)", f["name"], f["token"])
            return f["token"]
    return None


def create_monthly_sheet(token: str, template_token: str, folder_token: str,
                         year: int, month: int) -> str:
    """Copy the template spreadsheet and set up dates for the target month.

    Returns the new spreadsheet token.
    """
    title = _month_file_name(year, month)
    logger.info("Creating new monthly sheet: %s", title)

    # Copy the template
    data = _api(token, "post", f"/drive/v1/files/{template_token}/copy",
        json={
            "name": title,
            "type": "sheet",
            "folder_token": folder_token,
        },
    )
    new_token = data["data"]["file"]["token"]
    logger.info("Copied template → %s (token=%s)", title, new_token)

    # Get sheet tab IDs from the new spreadsheet
    sheets_data = _api(token, "get",
        f"/sheets/v3/spreadsheets/{new_token}/sheets/query")
    new_sheets = {s["title"]: s["sheet_id"] for s in sheets_data["data"]["sheets"]}

    # Fill in dates for each store tab
    days_in_month = calendar.monthrange(year, month)[1]
    for store in STORES:
        sheet_id = new_sheets.get(store)
        if not sheet_id:
            logger.warning("Sheet tab for %s not found in new spreadsheet", store)
            continue

        # Build date + weekday values for rows 6 to 6+days_in_month-1
        values = []
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            values.append([_excel_serial(d), _weekday_cn(d)])

        # Write B6:C{last_row}
        last_row = _HEADER_ROWS + days_in_month
        range_str = f"{sheet_id}!B{_HEADER_ROWS + 1}:C{last_row}"

        httpx.put(
            f"{_LARK_BASE}/sheets/v2/spreadsheets/{new_token}/values",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"valueRange": {"range": range_str, "values": values}},
            timeout=15,
        )
        logger.info("  %s: wrote %d date rows", store, days_in_month)

    return new_token


# ── Fill turnover and table data ──────────────────────────────────────────────

def fill_turnover_data(token: str, sheet_token: str, report_date: date,
                       turnover_data: dict[str, float],
                       tables_data: dict[str, float]) -> None:
    """Write 翻台率 and 总桌数 for a specific date across all store tabs."""

    # Get sheet tab IDs
    sheets_data = _api(token, "get",
        f"/sheets/v3/spreadsheets/{sheet_token}/sheets/query")
    store_sheets = {s["title"]: s["sheet_id"] for s in sheets_data["data"]["sheets"]}

    # Calculate which row this date maps to
    row = _HEADER_ROWS + report_date.day  # day 1 = row 6, day 2 = row 7, etc.

    for store in STORES:
        sheet_id = store_sheets.get(store)
        if not sheet_id:
            continue

        turnover = turnover_data.get(store, 0)
        tables = tables_data.get(store, 0)

        # Write D{row}:E{row}
        range_str = f"{sheet_id}!D{row}:E{row}"
        httpx.put(
            f"{_LARK_BASE}/sheets/v2/spreadsheets/{sheet_token}/values",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"valueRange": {"range": range_str, "values": [[turnover, tables]]}},
            timeout=15,
        )
        logger.debug("  %s row %d: 翻台率=%.2f 总桌数=%.0f", store, row, turnover, tables)

    logger.info("Filled turnover/tables data for %s", report_date)


# ── Check unfilled blue columns ───────────────────────────────────────────────

def check_unfilled(token: str, sheet_token: str, today: date) -> dict[str, list[date]]:
    """Check which stores have unfilled blue columns for past dates.

    Returns {store_name: [list of dates with missing data]}.
    """
    sheets_data = _api(token, "get",
        f"/sheets/v3/spreadsheets/{sheet_token}/sheets/query")
    store_sheets = {s["title"]: s["sheet_id"] for s in sheets_data["data"]["sheets"]}

    unfilled: dict[str, list[date]] = {}

    for store in STORES:
        sheet_id = store_sheets.get(store)
        if not sheet_id:
            continue

        # Read blue columns (F-K) for all days up to yesterday
        yesterday = today - timedelta(days=1)
        if yesterday.day < 1:
            continue

        first_row = _HEADER_ROWS + 1   # day 1
        last_row = _HEADER_ROWS + yesterday.day  # up to yesterday

        range_str = f"{sheet_id}!F{first_row}:K{last_row}"
        resp = httpx.get(
            f"{_LARK_BASE}/sheets/v2/spreadsheets/{sheet_token}/values/{range_str}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("valueRange", {}).get("values", [])

        missing_dates = []
        for day_offset, row in enumerate(rows):
            d = date(today.year, today.month, day_offset + 1)
            # Check if ALL blue cells are empty for this day
            all_empty = all(
                (cell is None or cell == "" or cell == 0)
                for cell in (row if row else [])
            )
            if all_empty:
                missing_dates.append(d)

        if missing_dates:
            unfilled[store] = missing_dates

    return unfilled


# ── Notifications ─────────────────────────────────────────────────────────────

def send_unfilled_alert(token: str, chat_id: str, unfilled: dict[str, list[date]],
                        sheet_url: str) -> None:
    """Send a Lark card listing stores with unfilled staffing data."""
    lines = [f"**📋 以下门店有未填写的用工数据：**\n"]

    for store, dates in sorted(unfilled.items()):
        date_strs = ", ".join(d.strftime("%m/%d") for d in dates[:7])
        extra = f" 等{len(dates)}天" if len(dates) > 7 else ""
        lines.append(f"▸ **{store}**：{date_strs}{extra}")

    lines.append(f"\n[👉 点击填写]({sheet_url})")
    lines.append("\n> 请门店尽快完成蓝色列数据填写")

    card = json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚠️ 用工数据未填写提醒"},
            "template": "yellow",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        ],
    })

    httpx.post(
        f"{_LARK_BASE}/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}"},
        json={"receive_id": chat_id, "msg_type": "interactive", "content": card},
        timeout=15,
    )
    logger.info("Sent unfilled alert for %d stores", len(unfilled))


def send_data_filled_summary(token: str, chat_id: str, report_date: date,
                             turnover: dict[str, float], tables: dict[str, float]) -> None:
    """Send a summary of today's filled data."""
    lines = [f"**✅ {report_date.strftime('%Y-%m-%d')} 翻台率/总桌数已自动填入**\n"]
    for store in STORES:
        t = turnover.get(store, 0)
        tb = tables.get(store, 0)
        lines.append(f"▸ {store}：翻台率 {t:.2f}　总桌数 {tb:.0f}")

    card = json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📊 用工表数据已更新"},
            "template": "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        ],
    })

    httpx.post(
        f"{_LARK_BASE}/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}"},
        json={"receive_id": chat_id, "msg_type": "interactive", "content": card},
        timeout=15,
    )


# ── Load daily report data ────────────────────────────────────────────────────

def load_daily_data(report_date: date) -> tuple[dict[str, float], dict[str, float]]:
    """Load turnover rate and table count from the daily store report database.

    Returns (turnover_by_store, tables_by_store).
    """
    try:
        from server.db import get_db, is_db_available
    except ImportError:
        logger.warning("server.db not available — cannot load daily data from DB")
        return {}, {}

    if not is_db_available():
        logger.warning("Database not available — returning empty data")
        return {}, {}

    db = get_db()
    if db is None:
        return {}, {}

    # The daily report stores QBI data in output files, not DB.
    # We need to read the QBI XLSX directly — but for now, we can pull
    # from the same source the daily report uses.
    # Simplest approach: read the latest generated report XLSX.
    from pathlib import Path
    report_path = Path(os.environ.get("OUTPUT_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "output"))
    ) / "daily-report" / f"database_report_{report_date.year}_{report_date.month:02d}_{report_date.day:02d}.xlsx"

    if not report_path.exists():
        logger.warning("Daily report not found at %s", report_path)
        return {}, {}

    import openpyxl
    wb = openpyxl.load_workbook(report_path, data_only=True)
    # The 对比上月表 (Sheet 1) has turnover rate and table count per store
    ws = wb.worksheets[0]  # 对比上月表

    turnover: dict[str, float] = {}
    tables: dict[str, float] = {}

    # Find the turnover rate and tables rows — scan for matching labels
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=False):
        first_cell = row[0].value if row[0].value else ""
        if "翻台率" in str(first_cell) and "考核" in str(first_cell):
            # This row has turnover rates per store (columns match store order)
            for i, store in enumerate(STORES):
                cell = row[i + 1] if i + 1 < len(row) else None
                if cell and cell.value is not None:
                    turnover[store] = float(cell.value)
        elif str(first_cell).strip() == "营业桌数(考核)":
            for i, store in enumerate(STORES):
                cell = row[i + 1] if i + 1 < len(row) else None
                if cell and cell.value is not None:
                    tables[store] = float(cell.value)

    wb.close()
    return turnover, tables


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Store working-hour data collection")
    parser.add_argument("--date", type=str, default=None,
                        help="Check date YYYY-MM-DD (default: yesterday)")
    args = parser.parse_args()

    app_id = os.environ.get("LARK_APP_ID", "")
    app_secret = os.environ.get("LARK_APP_SECRET", "")
    chat_id = os.environ.get("HOURS_NOTIFY_CHAT_ID", "")
    template_token = os.environ.get("HOURS_TEMPLATE_TOKEN", TEMPLATE_TOKEN)
    folder_token = os.environ.get("HOURS_FOLDER_TOKEN", FOLDER_TOKEN)

    if not app_id or not app_secret:
        logger.error("LARK_APP_ID and LARK_APP_SECRET must be set")
        sys.exit(1)
    if not chat_id:
        logger.error("HOURS_NOTIFY_CHAT_ID must be set")
        sys.exit(1)

    from lark_client import LarkClient
    with LarkClient(app_id=app_id, app_secret=app_secret) as client:
        token = client._get_token()

    # Report date = yesterday (we fill in yesterday's data each morning)
    report_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    today = date.today()
    year, month = report_date.year, report_date.month

    logger.info("Processing date: %s (month: %04d-%02d)", report_date, year, month)

    # Step 1: Find or create the monthly spreadsheet
    sheet_token = find_monthly_sheet(token, folder_token, year, month)
    if not sheet_token:
        sheet_token = create_monthly_sheet(token, template_token, folder_token, year, month)

    sheet_url = f"https://haidilao.feishu.cn/sheets/{sheet_token}"

    # Step 2: Load and fill turnover/tables data
    turnover, tables_count = load_daily_data(report_date)
    if turnover and tables_count:
        fill_turnover_data(token, sheet_token, report_date, turnover, tables_count)
        send_data_filled_summary(token, chat_id, report_date, turnover, tables_count)
    else:
        logger.warning("No daily data available for %s — skipping fill", report_date)

    # Step 3: Check for unfilled blue columns and alert
    if today.month == month:  # only check current month
        unfilled = check_unfilled(token, sheet_token, today)
        if unfilled:
            send_unfilled_alert(token, chat_id, unfilled, sheet_url)
        else:
            logger.info("All stores have filled staffing data up to yesterday ✓")

    logger.info("Done")


if __name__ == "__main__":
    main()
