# Store Hours Collect

Daily automation that manages monthly Feishu spreadsheets tracking store working-hour data (翻台率, 总桌数, and staffing columns).

**Runs:** 06:30 AM Vancouver (`America/Vancouver`) via APScheduler  
**Manual trigger:** `GET /api/reports/store-hours/check/{date}`  
**Production chat:** `oc_9fe9a845d25c1e07a58a1230cbb04b5d`

---

## What It Does

1. **Find or create the monthly spreadsheet** — looks in the target Feishu folder for `加拿大门店用工数据跟踪-YYYYMM`. If not found, copies the template and fills date/weekday rows (cols B–C) for all days in the month.

2. **Fill 翻台率 (col D) + 总桌数 (col E)** — scans all dates from day 1 to **T−2** (two days before the run date). For each date missing data, reads the daily report XLSX and writes values to all 8 store tabs.

3. **Check blue columns (F–K) for unfilled staffing data** — reads the same date range. Any store tabs with entirely empty F–K rows are flagged.

4. **Send Lark alerts:**
   - Green card: dates that were newly filled in (翻台率 + 总桌数 summary)
   - Yellow card: stores/dates with missing staffing data (if any)

---

## T−2 Logic

If today is **2026-03-18**, the target date is **2026-03-16**. This gives stores 2 days to enter the previous day's data before the check runs.

---

## Data Source

Reads generated daily report XLSX files from:

```
output/daily-report/database_report_YYYY_MM_DD.xlsx
```

If the XLSX for a given date doesn't exist on disk, the job generates it **directly via subprocess** (not via the server's run queue, to avoid deadlocking the serial execution queue):

```bash
uv run --project projects/daily-store-operation-report \
    python -m daily_store_operation_report.main <date>
```

The subprocess has a 300-second timeout. If the VPN is down or the generation fails, that date is skipped and a warning is logged.

---

## Feishu Setup

| Resource | Token |
|----------|-------|
| Template spreadsheet | `SbTns7kTxhxn5TtLMyccOrqRnqe` |
| Target folder | `AVt8fGZLHl5PzJd2gw3cNa10ntd` |

The template has 8 tabs, one per store:
> 加拿大一店, 加拿大二店, 加拿大三店, 加拿大四店, 加拿大五店, 加拿大六店, 加拿大七店, 加拿大八店

Sheet layout:
- Rows 1–5: headers
- Row 6 onwards: one row per calendar day
- Col B: Excel serial date, Col C: 星期X
- Col D: 翻台率, Col E: 总桌数 ← auto-filled by this job
- Cols F–K: staffing data ← filled by store staff, checked by this job

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `LARK_APP_ID` | Feishu bot application ID |
| `LARK_APP_SECRET` | Feishu bot application secret |
| `HOURS_NOTIFY_CHAT_ID` | Lark group chat ID for notifications |
| `HOURS_TEMPLATE_TOKEN` | Template spreadsheet token (default: `SbTns7kTxhxn5TtLMyccOrqRnqe`) |
| `HOURS_FOLDER_TOKEN` | Target folder token (default: `AVt8fGZLHl5PzJd2gw3cNa10ntd`) |

---

## Manual Run

```bash
# Check/fill data for T-2 (default)
uv run --project projects/store-hours-collect python -m store_hours_collect.main

# Check/fill data for a specific date
uv run --project projects/store-hours-collect python -m store_hours_collect.main --date 2026-03-16
```

Via HTTP:

```
GET /api/reports/store-hours/check/2026-03-16
```

---

## Dependencies

```
projects/store-hours-collect
    ├── depends on → libs/lark-client    (Feishu token + messaging)
    ├── depends on → httpx               (Feishu Sheets API calls)
    ├── depends on → openpyxl            (read daily report XLSX)
    └── depends on → python-dotenv       (env config)
```

The job also spawns `daily-store-operation-report` as a subprocess when needed.

---

## Code Notes

- **Excel serial date**: `(d - date(1900, 1, 1)).days + 2` — the +2 accounts for Excel's 1900 leap-year bug and 1-based offset. Correct for all dates in the modern range.
- **Thread safety**: runs from the server's serial asyncio queue — only one automation runs at a time.
- **Subprocess deadlock avoidance**: calling `ensure_daily_report()` via subprocess (not queue) prevents the serial queue from blocking itself.
- **Lark API errors**: all GET/PUT/POST helpers check `code != 0` and raise `RuntimeError` with the error details. Notification send failures are logged as errors (non-fatal).
