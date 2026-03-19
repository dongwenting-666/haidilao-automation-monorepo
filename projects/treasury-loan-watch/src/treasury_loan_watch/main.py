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

import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_TOKEN   = "T8NosM6aRhj8v0t6JA8cugS9nYb"
SHEET_TAB_ID  = "16yYcs"

# Column indices (0-based) in the data sheet
_COL_SEQ      = 0   # 序号
_COL_DATE     = 1   # 日期 (loan issue date)
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


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class LoanRecord:
    seq: int
    lender: str
    borrower: str
    company_code: str | int
    currency: str
    amount: float
    rate: float
    start_date: date
    maturity_date: date
    term: str
    interest: float | str


# ── Excel date conversion ─────────────────────────────────────────────────────

def _excel_to_date(serial: int | float) -> date:
    """Convert an Excel serial date number to a Python date.

    Excel counts from 1900-01-01 = 1, with a leap-year bug on day 60
    (1900-02-29 doesn't exist but Excel treats it as valid), so we subtract 2.
    """
    return date(1900, 1, 1) + timedelta(days=int(serial) - 2)


# ── Sheet reader ──────────────────────────────────────────────────────────────

def fetch_loans(token: str, sheet_token: str, sheet_id: str) -> list[LoanRecord]:
    """Fetch all loan rows from the Feishu sheet and return parsed records.

    Skips the title row (row 1) and header row (row 2).
    Skips rows with non-numeric maturity dates (formula cells, blanks).
    """
    resp = httpx.get(
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_token}/values/{sheet_id}!A1:L1048",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json().get("data", {}).get("valueRange", {}).get("values", [])

    records: list[LoanRecord] = []
    for row in rows[2:]:  # skip title + header
        if not row or len(row) <= _COL_MATURITY:
            continue

        maturity_raw = row[_COL_MATURITY]
        if not isinstance(maturity_raw, (int, float)):
            continue  # skip formula strings or blank cells

        start_raw = row[_COL_START]
        if not isinstance(start_raw, (int, float)):
            continue

        try:
            records.append(LoanRecord(
                seq=row[_COL_SEQ] if len(row) > _COL_SEQ else 0,
                lender=str(row[_COL_LENDER]) if len(row) > _COL_LENDER else "",
                borrower=str(row[_COL_BORROWER]) if len(row) > _COL_BORROWER else "",
                company_code=row[_COL_CODE] if len(row) > _COL_CODE else "",
                currency=str(row[_COL_CURRENCY]) if len(row) > _COL_CURRENCY else "",
                amount=float(row[_COL_AMOUNT]) if len(row) > _COL_AMOUNT else 0,
                rate=float(row[_COL_RATE]) if len(row) > _COL_RATE else 0,
                start_date=_excel_to_date(start_raw),
                maturity_date=_excel_to_date(maturity_raw),
                term=str(row[_COL_TERM]) if len(row) > _COL_TERM else "",
                interest=row[_COL_INTEREST] if len(row) > _COL_INTEREST else "",
            ))
        except Exception as e:
            logger.debug("Skipping unparseable row %s: %s", row, e)

    return records


# ── Notification ──────────────────────────────────────────────────────────────

def _format_amount(amount: float, currency: str) -> str:
    if currency.upper() == "USD":
        return f"USD {amount:,.0f}"
    elif currency.upper() == "CNY":
        return f"¥{amount:,.0f}"
    return f"{currency} {amount:,.0f}"


def build_card(due_loans: list[LoanRecord], today: date) -> str:
    """Build a Lark card JSON string for the due loans."""
    import json

    lines = [f"**📅 {today.strftime('%Y-%m-%d')}  共 {len(due_loans)} 笔贷款今日到期**\n"]

    for loan in due_loans:
        rate_pct = f"{loan.rate * 100:.2f}%" if loan.rate < 1 else f"{loan.rate:.2f}%"
        lines.append(
            f"▸ **{loan.borrower}** ({loan.company_code})\n"
            f"  金额：{_format_amount(loan.amount, loan.currency)}　"
            f"利率：{rate_pct}　"
            f"借款日：{loan.start_date}　到期日：{loan.maturity_date}\n"
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
    import json
    from lark_client import LarkClient

    app_id = os.environ["LARK_APP_ID"]
    app_secret = os.environ["LARK_APP_SECRET"]

    with LarkClient(app_id=app_id, app_secret=app_secret) as client:
        token = client._get_token()
        card_content = build_card(due_loans, today)

        resp = httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": card_content,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Lark API error: {result}")
        logger.info("Notification sent for %d due loans", len(due_loans))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

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

    from lark_client import LarkClient
    with LarkClient(app_id=app_id, app_secret=app_secret) as client:
        token = client._get_token()

    today = date.today()
    logger.info("Checking loan maturities for %s", today)

    loans = fetch_loans(token, sheet_token, sheet_id)
    logger.info("Loaded %d loan records", len(loans))

    due_today = [loan for loan in loans if loan.maturity_date == today]
    logger.info("%d loan(s) due today", len(due_today))

    if not due_today:
        logger.info("No loans due today — nothing to notify")
        return

    send_notification(chat_id, due_today, today)
    logger.info("Done")


if __name__ == "__main__":
    main()
