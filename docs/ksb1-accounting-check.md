# KSB1 Accounting Check (`projects/ksb1-accounting-check`)

Downloads KSB1 cost center data from SAP and generates a month-over-month comparison report per store.

## Module Structure

```
projects/ksb1-accounting-check/
├── src/ksb1_accounting_check/
│   ├── main.py        # CLI entry point (argparse, orchestration)
│   ├── analyze.py     # Data loading, enrichment, report generation (XLSX)
│   ├── rules.py       # Deterministic rule-based analysis
│   ├── llm.py         # Optional LLM enhancement for findings
│   ├── prompt.md      # LLM enhancer prompt
│   └── 报表科目.xlsx   # Cost element → 报表科目 mapping
├── tests/
│   └── test_rules.py  # Unit tests for rules.py (19 tests)
└── pyproject.toml
```

## CLI Usage

```bash
# Default: check previous month, download from SAP
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Specific month/year
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main 1 2026

# Skip SAP download, reuse existing export
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --skip-download

# Enable LLM enhancement (requires Ollama running locally)
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --model qwen3:8b
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `month` | Previous month | Month to check (1-12) |
| `year` | Current year | Year |
| `--username` | `$SAP_USERNAME` | SAP login username |
| `--password` | `$SAP_PASSWORD` | SAP login password |
| `--output-dir` | `<repo>/output` | Output directory |
| `--skip-download` | `false` | Skip SAP download, use existing file |
| `--model` | `None` | Ollama model for LLM enhancement (e.g., `qwen3:8b`) |
| `--language` | `ZH` | SAP logon language |

## Pipeline

### Step 1: SAP Download

Downloads KSB1 for a 2-month date range (previous month + target month) into `output/<year-month>/ksb1-<year-month>.XLSX`. Uses the `sap-gui` library's KSB1 process module.

### Step 2: Report Generation

1. **Load mapping** — `报表科目.xlsx` maps 成本要素 codes to 报表科目 categories
2. **Load KSB1 data** — Read raw SAP export into row dicts
3. **Enrich rows** — Add `月份` (from 过账日期) and `科目` (from mapping) to each row (mutates in place)
4. **Split by month** — Separate into previous month and current month rows
5. **Filter stores** — Match against `DEFAULT_STORE_KEYWORDS` (销售公共组 1-8)
6. **Per-store analysis:**
   - Build 科目 summary with 成本要素名称-level breakdown
   - Run deterministic rules (`rules.py`)
   - [Optional] Enhance findings with LLM (`llm.py`)
   - Write findings sheet with observation + detail rows
7. **Write raw data sheet** — All enriched rows for reference
8. **Write mapping sheet** — Copy of 报表科目 mapping

### Output Format

The report is an XLSX workbook with:

| Sheet | Content |
|-------|---------|
| Per-store sheets (e.g., "一店销售公共组") | Findings with detail rows underneath each observation |
| 原数据（X月&Y月） | All enriched transaction rows |
| 报表科目 | Cost element mapping reference |

## Analysis Rules (`rules.py`)

All rule-based analysis is **deterministic** — no LLM, no randomness. Same input always produces the same output.

### Skipped Kemus

High-volume routine items excluded entirely:
- 23、物料消耗
- 33、资产折旧费
- 15、员工餐费用

### Rule 1: Previous Month Only

Cost element present last month but absent this month.

> 电费12月有1,000.00CAD，1月无

### Rule 2: Current Month Only (New)

Cost element absent last month but present this month.

> 清洁费1月新增2,000.00CAD，12月无

### Rule 3: Amount Difference

Two tiers based on whether the cost element is "key":

**Key cost elements** (matched case-insensitively as substring):
`电费`, `车辆保险`, `清洁费`, `燃料费`, `燃气费`, `税`, `财产保险`, `保险费`, `咨询服务`, `租赁费`, `房租`, `宿舍租赁`, `水电气`, `水费`, `宿舍水电燃`, `工资`, `IOT`, `Opentable`, `神秘嘉宾`

| Condition | Threshold |
|-----------|-----------|
| Key element | Absolute difference >= 100 CAD |
| Non-key element | Absolute difference >= 500 CAD **AND** percentage change >= 20% |

> 电费1月比12月多500.00（增加50.0%）

### Currency

All amounts use `对象货币值` (object currency / local CAD), not `报表货币值` (reporting currency / CNY).

### Detail Rows

Each finding includes transaction detail rows underneath, showing `月份`, `对象货币值`, and `名称`. Rows with identical `名称` within the same month are aggregated (e.g., "采购入库等3笔"); otherwise individual transactions are shown.

## LLM Enhancement (`llm.py`)

Optional hybrid approach: rules detect anomalies, LLM explains **why** they exist.

### How It Works

1. Rules run first and produce findings (deterministic)
2. For each finding, transaction detail rows are grouped and subtotals pre-computed
3. Findings are batched (max 4000 chars per batch) and sent to the LLM
4. LLM receives the finding observation + pre-computed subtotals, and rewrites the observation with contextual explanation
5. Enhanced observations are merged back, preserving original `kemu_list` and `cost_elements`
6. On LLM failure (timeout, parse error), falls back to original rule-based observation

### Key Design Decisions

- **Pre-computed subtotals**: The LLM never does arithmetic. All amounts are grouped by name/month and summed before being sent to the LLM. This prevents calculation errors.
- **Graceful fallback**: Each batch has independent retry logic (max 2 retries). Failed batches use original rule text.
- **Prompt path override**: `set_prompt_path()` allows overriding the prompt file location (used by PyInstaller bundles).

### Configuration

- `model`: Ollama model name (e.g., `qwen3:8b`, `qwen3:14b`, `qwen3:32b`)
- Leave model empty/None for rules-only analysis (recommended for speed)

## Testing

```bash
python -m pytest projects/ksb1-accounting-check/tests/ -v
```

19 tests covering:
- `_is_key_element`: exact match, substring, case-insensitive, non-match
- Rule 1 (prev only) and Rule 2 (curr only) findings
- Rule 3: key element above/below threshold, match via kemu name
- Rule 3: non-key above both thresholds, below abs, below pct, decrease
- Edge cases: zero diff, prev=0 with curr!=0, both zero
- `analyze_store`: skipped kemus, multiple kemus, finding structure
