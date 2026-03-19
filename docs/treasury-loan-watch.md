# Treasury Loan Watch

Daily automated check for TREASURY inter-company loan maturities. Reads loan records from a Feishu spreadsheet, identifies loans maturing today, and sends a Lark card notification to a configured group chat.

---

## Purpose

The `treasury-loan-watch` project ensures that TREASURY inter-company loans reaching maturity are surfaced to the relevant team daily at 6:00 AM Vancouver time. It reads maturity dates from a Feishu sheet, finds any loans due today, and sends a structured Lark card if any are found.

---

## Data Source

| Field | Value |
|-------|-------|
| Feishu Sheet Token | `T8NosM6aRhj8v0t6JA8cugS9nYb` |
| Tab ID | `16yYcs` |
| Tab Name | `data` |

### Sheet Columns

| Column (Chinese) | Meaning |
|-----------------|---------|
| 序号 | Row number |
| 日期 | Record date |
| 放款公司 | Lender company |
| 借款公司 | Borrower company |
| 公司代码 | Company code |
| 币种 | Currency |
| 借款金额 | Loan amount |
| 借款利率 | Interest rate |
| 借款日 | Loan start date |
| 到期日 | Maturity date |
| 借款期限 | Loan term |
| 利息总额 | Total interest |

---

## Logic

1. Authenticates with Feishu using `LARK_APP_ID` / `LARK_APP_SECRET`
2. Reads all rows from the data sheet
3. Parses the `到期日` column — stored as **Excel serial date integers** — and converts to calendar dates
4. Finds all rows where maturity date equals today's date (Vancouver time)
5. If any matching loans are found, sends a Lark card to `TREASURY_NOTIFY_CHAT_ID`
6. If no loans mature today, exits silently

---

## Lark Card Format

- **Header colour:** Red
- **Header title:** `💰 TREASURY 贷款到期提醒`
- **Body:** One entry per maturing loan, listing:
  - 借款公司 (borrower)
  - 借款金额 and 币种 (amount and currency)
  - 借款利率 (interest rate)
  - 借款日 → 到期日 (start date → maturity date)

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LARK_APP_ID` | ✅ | Lark bot application ID |
| `LARK_APP_SECRET` | ✅ | Lark bot application secret |
| `TREASURY_NOTIFY_CHAT_ID` | ✅ | Lark group chat ID to send maturity alerts |
| `TREASURY_SHEET_TOKEN` | Optional | Override the default Feishu sheet token |
| `TREASURY_SHEET_ID` | Optional | Override the default sheet tab ID |

All variables are loaded from `.env` in the repo root.

---

## Running Manually

```bash
uv run --project projects/treasury-loan-watch python -m treasury_loan_watch.main
```

---

## Scheduled Execution

The project is registered in the server scheduler and runs automatically at **06:00 America/Vancouver** every day.

To check scheduled jobs:

```bash
GET /api/jobs
```

---

## API Trigger

The run can also be triggered on-demand via the server API:

```bash
POST /api/runs
Content-Type: application/json

{"command": "treasury-loan-watch"}
```

The response includes a `run_id` which can be polled at `GET /api/runs/{run_id}` for status and logs.

---

## Dependencies

| Dependency | Purpose |
|-----------|---------|
| `lark-client` | Feishu sheet read + Lark card delivery |
| `python-dotenv` | `.env` loading |
