# inventory-check

Monthly 盘点结果 (inventory result) generator for the Canada region.

## What it does

For a given month, produces a per-store `CA0X-盘点结果-YYYYMM.xlsx` workbook
shaped exactly like the manual one — same sheets, same formulas, same
hand-curated reference tabs (`计算`, `分类`, `BI套餐`, `折算数量`,
`对照表`) inherited from a chosen template.

The four data-bearing sheets are regenerated from live sources:

| Sheet | Source |
|---|---|
| `本月系统单价mb5b` | SAP MB5B (region-wide, filtered to store werks) |
| `上月数量zfi0156` + `上月数量需更新` | SAP ZFI0156 from prior month (filtered to store werks) |
| `红火台销售汇总` + `Sheet3` (POS pivot) | POS 菜品销售汇总 (per-store) |
| `CA08-本月-盘点结果.` (the report) | Built from MB5B + Fiori 盘点录入 + ZFI0156 + POS |

When the target store ≠ the template-native store (i.e. anything other
than CA08 if using the CA08 template), the inherited reference sheets
are wiped so each workbook is fully self-contained.

## Single-store run

```bash
uv run --project projects/inventory-check python -m inventory_check.main \
    --store CA8DKG --month 2026-04 \
    --template-file ~/Downloads/CA08-盘点结果-202603.xlsx \
    --fiori-source entry
```

`--fiori-source entry` is needed early in the month (before ops finishes
the count and archives it). Switch to `archive` (the default) once the
month's count is posted.

## All-stores run (preferred)

For monthly batch use:

```bash
# 1. Wake silent OAuth (once — Chrome stays running between runs)
scripts/start-chrome-cdp.sh

# 2. Pre-download MB5B + ZFI0156 once (region-wide; reused by all stores)
uv run --project projects/inventory-check python -m inventory_check.main \
    --store CA8DKG --month 2026-04 --no-assemble

# 3. Run all stores
uv run --project projects/inventory-check python -m inventory_check.all_stores \
    --month 2026-04 \
    --template ~/Downloads/CA08-盘点结果-202603.xlsx
```

Output lands in `output/inventory-check/<period>-all/<werks>/`.

### Skipped stores

`CA3DKG` and `CA5DKG` are skipped by default:

- **CA03**: no Fiori 盘点录入 entry — store doesn't run the cycle there.
- **CA05**: Fiori login fails. Credential is configured in `.env`
  (`SGPFIORIWEB_CREDS["CA5DKG"]`) but the login flow rejects it.
  Investigated 2026-05; root cause not pinned down. Run manually if
  needed.

Override via `--skip ""` (try everyone) or `--stores CA1DKG,CA2DKG`
(explicit subset).

## How POS auth avoids the QR scan

POS (`pos.superhi-tech.com`) uses Feishu SSO with a 17-minute server-side
TTL on the session cookie — too short to cache reliably. The all-stores
driver attaches via Chrome DevTools Protocol to a dedicated Chrome
launched by `scripts/start-chrome-cdp.sh`. That Chrome holds a snapshot
of cookies/Local Storage from your real Chrome profile, so 飞书授权登录
silent-grants without a QR scan.

If silent OAuth fails (cookie snapshot stale), the driver falls through
to the QR-scan prompt. Re-snapshot by deleting `~/.haidilao/chrome-cdp`
and re-running `scripts/start-chrome-cdp.sh`.

## Tests

```bash
uv run pytest projects/inventory-check/tests/ -q
```

E2E paths (browser, SAP GUI, Fiori) aren't covered by the unit suite.
Manual e2e: run a known-good month and diff `Sheet3` keys + `计算!M`
values against the existing manual workbook.
