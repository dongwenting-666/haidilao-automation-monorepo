"""Treasury loan maturity watch.

Reads the TREASURY loan sheet from Feishu and sends a Lark message
for any loans whose 到期日 (maturity date) is today.

Run:
    uv run --project projects/treasury-loan-watch python -m treasury_loan_watch.main

Environment variables (via .env or LaunchAgent):
    LARK_APP_ID             Feishu bot app ID
    LARK_APP_SECRET         Feishu bot app secret
    TREASURY_SHEET_TOKEN    Spreadsheet token (default: T8NosM6aRhj8v0t6JA8cugS9nYb)
    TREASURY_SHEET_ID       Sheet tab ID     (default: 16yYcs)
    TREASURY_NOTIFY_CHAT_ID Lark group chat open_chat_id to notify
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_TOKEN  = "T8NosM6aRhj8v0t6JA8cugS9nYb"
SHEET_TAB_ID = "16yYcs"

# Column indices (0-based) in the data sheet
_COL_SEQ      = 0   # 序号
_COL_LENDER   = 2   # 放款公司
_COL_BORROWER = 3   # 借款公司
_COL_CODE     = 4   # 公司代码
_COL_CURRENCY = 5   # 币种
_COL_AMOUNT   = 6   # 借款金额
_COL_RATE     = 7   # 借款利率
_COL_START    = 8   # 借款日
_COL_MATURITY = 9   # 到期日  ← key field
_COL_TERM     = 10  # 借款期限
_COL_INTEREST = 11  # 利息总额

# Range to fetch — L column, up to row 1048 (well beyond the 792 current rows)
_FETCH_RANGE = "A1:L1048"


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class LoanRecord:
    seq: int | str
    lender: str
    borrower: str
    company_code: str | int
    currency: str
    amount: float
    rate: float
    start_date: date
    maturity_date: date
    term: str


# ── Excel date conversion ─────────────────────────────────────────────────────

def _excel_to_date(serial: int | float) -> date:
    """Convert an Excel serial date number to a Python date.

    Excel counts from 1900-01-01 = 1, with a leap-year bug on day 60
    (1900-02-29 doesn't exist but Excel treats it as valid), so we subtract 2.
    """
    return date(1900, 1, 1) + timedelta(days=int(serial) - 2)


def _safe_float(val: object, default: float = 0.0) -> float:
    """Coerce a cell value to float, returning *default* on failure."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_str(val: object, default: str = "") -> str:
    if val is None:
        return default
    return str(val)


def _safe_col(row: list, idx: int, default: object = None) -> object:
    """Safely get a column from a row that may be shorter than expected."""
    return row[idx] if idx < len(row) else default


# ── Sheet reader ──────────────────────────────────────────────────────────────

def fetch_loans(token: str, sheet_token: str, sheet_id: str) -> list[LoanRecord]:
    """Fetch all loan rows from the Feishu sheet and return parsed records.

    Skips the title row (row 1) and header row (row 2).
    Skips rows with non-numeric maturity dates (formula cells, blanks).
    """
    import httpx

    resp = httpx.get(
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_token}"
        f"/values/{sheet_id}!{_FETCH_RANGE}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu sheet API error: code={data.get('code')} msg={data.get('msg')}")

    rows = data.get("data", {}).get("valueRange", {}).get("values", [])
    if len(rows) < 3:
        logger.warning("Sheet has fewer than 3 rows — no data to process")
        return []

    records: list[LoanRecord] = []
    for row_idx, row in enumerate(rows[2:], start=3):  # skip title + header
        if not row or len(row) <= _COL_MATURITY:
            continue

        maturity_raw = _safe_col(row, _COL_MATURITY)
        start_raw = _safe_col(row, _COL_START)

        # Skip rows where dates are not numeric (formulas, blanks, strings)
        if not isinstance(maturity_raw, (int, float)):
            continue
        if not isinstance(start_raw, (int, float)):
            continue

        try:
            records.append(LoanRecord(
                seq=_safe_col(row, _COL_SEQ, 0),
                lender=_safe_str(_safe_col(row, _COL_LENDER)),
                borrower=_safe_str(_safe_col(row, _COL_BORROWER)),
                company_code=_safe_col(row, _COL_CODE, ""),
                currency=_safe_str(_safe_col(row, _COL_CURRENCY)),
                amount=_safe_float(_safe_col(row, _COL_AMOUNT)),
                rate=_safe_float(_safe_col(row, _COL_RATE)),
                start_date=_excel_to_date(start_raw),
                maturity_date=_excel_to_date(maturity_raw),
                term=_safe_str(_safe_col(row, _COL_TERM)),
            ))
        except Exception as e:
            logger.debug("Skipping row %d: %s", row_idx, e)

    return records


# ── Notification ──────────────────────────────────────────────────────────────

def _format_amount(amount: float, currency: str) -> str:
    c = currency.upper()
    if c == "USD":
        return f"USD {amount:,.0f}"
    if c == "CNY":
        return f"¥{amount:,.0f}"
    return f"{currency} {amount:,.0f}"


def build_card(due_loans: list[LoanRecord], today: date) -> str:
    """Build a Lark interactive card JSON string for the due loans."""
    lines = [f"**📅 {today.strftime('%Y-%m-%d')}  共 {len(due_loans)} 笔贷款今日到期**\n"]

    for loan in due_loans:
        rate_pct = (
            f"{loan.rate * 100:.2f}%" if 0 < loan.rate < 1
            else f"{loan.rate:.2f}%"
        )
        lines.append(
            f"▸ **{loan.borrower}** ({loan.company_code})\n"
            f"  金额：{_format_amount(loan.amount, loan.currency)}　"
            f"利率：{rate_pct}　"
            f"期限：{loan.start_date} → {loan.maturity_date}\n"
        )

    lines.append("\n> ⚠️ 今日到期，需要处理")

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "💰 TREASURY 贷款到期提醒"},
            "template": "red",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        ],
    }
    return json.dumps(card)


def send_notification(chat_id: str, due_loans: list[LoanRecord], today: date) -> None:
    """Send the maturity alert card to the Lark group."""
    from lark_client import LarkClient

    app_id = os.environ["LARK_APP_ID"]
    app_secret = os.environ["LARK_APP_SECRET"]

    with LarkClient(app_id=app_id, app_secret=app_secret) as client:
        card_json = build_card(due_loans, today)
        client._post(
            "/im/v1/messages?receive_id_type=chat_id",
            {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": card_json,
            },
        )
    logger.info("Notification sent for %d due loans", len(due_loans))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Treasury loan maturity watch")
    parser.add_argument(
        "--date", type=str, default=None,
        help="Check date in YYYY-MM-DD format (default: today)",
    )
    args = parser.parse_args()

    app_id = os.environ.get("LARK_APP_ID", "")
    app_secret = os.environ.get("LARK_APP_SECRET", "")
    chat_id = os.environ.get("TREASURY_NOTIFY_CHAT_ID", "")
    sheet_token = os.environ.get("TREASURY_SHEET_TOKEN", SHEET_TOKEN)
    sheet_id = os.environ.get("TREASURY_SHEET_ID", SHEET_TAB_ID)

    if not app_id or not app_secret:
        logger.error("LARK_APP_ID and LARK_APP_SECRET must be set")
        sys.exit(1)
    if not chat_id:
        logger.error("TREASURY_NOTIFY_CHAT_ID must be set")
        sys.exit(1)

    # Get Lark tenant token for sheet API access
    from lark_client import LarkClient
    with LarkClient(app_id=app_id, app_secret=app_secret) as client:
        token = client._get_token()

    check_date = date.fromisoformat(args.date) if args.date else date.today()
    logger.info("Checking loan maturities for %s", check_date)

    loans = fetch_loans(token, sheet_token, sheet_id)
    logger.info("Loaded %d loan records", len(loans))

    due = [loan for loan in loans if loan.maturity_date == check_date]
    logger.info("%d loan(s) due on %s", len(due), check_date)

    if not due:
        logger.info("No loans due on %s — nothing to notify", check_date)
        return

    send_notification(chat_id, due, check_date)
    logger.info("Done")


if __name__ == "__main__":
    main()
