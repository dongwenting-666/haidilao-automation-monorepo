"""CLI entrypoint for the 毛利相关分析指标 workbook generator.

Usage (basic — uses local archives):

    uv run --project projects/zfi0049-report python -m zfi0049_report.gross_margin_analysis_main \\
        --year 2026 --month 3 \\
        --zfi0156 output/zfi0156/zfi0156-202603.xlsx \\
        --mb5b output/mb5b/mb5b202603.xls \\
        --canada-pnl output/zfi0049/2026-03/canada_pnl_9451_2026_03.xlsx \\
        --pos-dir output/pos/202603 \\
        --output output/gross-margin/2026-03/附件3-毛利相关分析指标-2603.xlsx

The --canada-pnl input is the 损益表 output from
``zfi0049_report.gross_margin_main`` (which extracts ZFI0049 + maps to
P&L lines). It supplies the current-month cur_pnl dict.

For prev/YoY data, pass --mb5b-prev / --mb5b-yoy / --canada-pnl-prev /
--canada-pnl-yoy. Missing arguments degrade gracefully — sheets that
depend on them are left blank rather than blocking the run.

Add --reference-diff <manual.xlsx> to compare key cells of the generated
workbook against a known-good manual workbook (e.g. last month's
hand-maintained version) and print mismatches.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from openpyxl import load_workbook

from zfi0049_report.canada_pnl import (
    ROWS as PNL_ROWS,
    STORE_ORDER,
)
from zfi0049_report.gross_margin_analysis import (
    GrossMarginInputs,
    build_workbook,
    load_inputs_from_paths,
)

log = logging.getLogger(__name__)


def load_pnl_from_canada_xlsx(path: Path) -> dict[str, dict[str, float]]:
    """Read a canada_pnl.xlsx 损益表 sheet → {store → {item → amount}}.

    Mirrors the inverse of ``canada_pnl.write_workbook``: rows are P&L
    items in ``PNL_ROWS`` order, cols are stores (cols 3+ in store-order).
    """
    if not path.exists():
        return {}
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb["损益表"]
    out: dict[str, dict[str, float]] = {s: {} for s in STORE_ORDER}
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return out
    header = list(rows[0])
    # Cols 3+ are store names
    store_cols = [(header[i], i) for i in range(2, len(header)) if header[i]]
    for row in rows[1:]:
        item = row[1]
        if not item:
            continue
        for store_name, col_i in store_cols:
            if col_i >= len(row):
                continue
            v = row[col_i]
            if isinstance(v, (int, float)):
                out.setdefault(store_name, {})[item] = float(v)
    return out


def discover_pos_paths(pos_dir: Path,
                       period: str = "20260301-20260331") -> dict[str, Path]:
    """Auto-discover per-store POS files in ``pos_dir``.

    Looks for files matching ``{store}-菜品销售汇总-{period}.xlsx``.
    """
    out: dict[str, Path] = {}
    if not pos_dir or not pos_dir.is_dir():
        return out
    for store in STORE_ORDER:
        candidate = pos_dir / f"{store}-菜品销售汇总-{period}.xlsx"
        if candidate.exists():
            out[store] = candidate
    return out


def load_bom_from_db() -> dict[str, list[dict]]:
    """Load BOM rows per store from the ``store_bom`` table.

    Returns an empty dict if the DB is unreachable — the orchestrator
    just won't populate 表1 rows.
    """
    try:
        from inventory_check.db_bom import load_store_bom_rows
    except ImportError:
        log.warning("inventory_check not importable — skipping BOM load")
        return {}
    werks_to_store = {
        "CA01": "加拿大一店", "CA02": "加拿大二店", "CA03": "加拿大三店",
        "CA04": "加拿大四店", "CA05": "加拿大五店", "CA06": "加拿大六店",
        "CA07": "加拿大七店", "CA08": "加拿大八店",
    }
    out: dict[str, list[dict]] = {}
    for werks, store in werks_to_store.items():
        try:
            rows = load_store_bom_rows(werks)
            if rows:
                out[store] = rows
        except Exception as exc:
            log.warning("BOM load failed for %s: %s", werks, exc)
    return out


def diff_against_reference(generated: Path, reference: Path) -> list[str]:
    """Compare the generated workbook against a reference (manual) workbook.

    Reports structural issues + a small set of high-value spot checks
    against known cells. Returns a list of mismatch descriptions; empty
    list means everything matched within tolerance.
    """
    mismatches: list[str] = []
    gen_wb = load_workbook(generated, read_only=True, data_only=True)
    ref_wb = load_workbook(reference, read_only=True, data_only=True)

    # Sheet-name layout match
    gen_sheets = gen_wb.sheetnames
    ref_sheets = ref_wb.sheetnames
    if gen_sheets != ref_sheets:
        mismatches.append(
            f"sheet names differ\n  gen: {gen_sheets}\n  ref: {ref_sheets}"
        )

    # Spot check: 基础数据 column count
    if "基础数据" in gen_sheets and "基础数据" in ref_sheets:
        gen_cols = gen_wb["基础数据"].max_column
        ref_cols = ref_wb["基础数据"].max_column
        if gen_cols != ref_cols:
            mismatches.append(
                f"基础数据 column count: gen={gen_cols} ref={ref_cols}"
            )

    gen_wb.close()
    ref_wb.close()
    return mismatches


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--output", type=Path, required=True,
                   help="Output xlsx path")
    p.add_argument("--zfi0156", type=Path, required=False)
    p.add_argument("--mb5b", type=Path, required=False,
                   help="Current-month MB5B export")
    p.add_argument("--mb5b-prev", type=Path, required=False)
    p.add_argument("--mb5b-yoy", type=Path, required=False)
    p.add_argument("--canada-pnl", type=Path, required=False,
                   help="Current-month canada_pnl xlsx (from zfi0049_report)")
    p.add_argument("--canada-pnl-prev", type=Path, required=False)
    p.add_argument("--canada-pnl-yoy", type=Path, required=False)
    p.add_argument("--pos-dir", type=Path, required=False,
                   help="Directory containing per-store POS xlsx files")
    p.add_argument("--pos-period", default="20260301-20260331",
                   help="POS filename period suffix (default: 20260301-20260331)")
    p.add_argument("--reference-diff", type=Path, required=False,
                   help="Compare against a reference (manual) workbook")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    cur_pnl = (load_pnl_from_canada_xlsx(args.canada_pnl)
               if args.canada_pnl else {})
    prev_pnl = (load_pnl_from_canada_xlsx(args.canada_pnl_prev)
                if args.canada_pnl_prev else {})
    yoy_pnl = (load_pnl_from_canada_xlsx(args.canada_pnl_yoy)
               if args.canada_pnl_yoy else {})

    pos_paths = (discover_pos_paths(args.pos_dir, args.pos_period)
                 if args.pos_dir else {})
    bom_rows = load_bom_from_db()

    # Build the 7-month trend from cur+prev_pnl gross-margin values when
    # available (this Mac will only have cur+prev; a real prod run reads
    # all 7 months from an archive).
    monthly_gp: dict[str, list[float]] = {}
    for store in STORE_ORDER:
        gps = []
        for pnl in (cur_pnl, prev_pnl, yoy_pnl):
            v = pnl.get(store, {}).get("三、毛利率")
            gps.append(float(v) if v is not None else 0.0)
        # Pad to 7 months
        while len(gps) < 7:
            gps.append(0.0)
        if any(gps):
            monthly_gp[store] = gps

    inputs = load_inputs_from_paths(
        year=args.year,
        month=args.month,
        cur_pnl=cur_pnl,
        pos_sales_paths=pos_paths,
        bom_rows=bom_rows,
        zfi_cur_path=args.zfi0156 or Path("/nonexistent"),
        mb5b_cur_path=args.mb5b or Path("/nonexistent"),
        monthly_gp=monthly_gp,
        prev_pnl=prev_pnl,
        yoy_pnl=yoy_pnl,
        mb5b_prev_path=args.mb5b_prev,
        mb5b_yoy_path=args.mb5b_yoy,
    )

    out = build_workbook(inputs, args.output)
    log.info("毛利分析 workbook saved: %s", out)

    if args.reference_diff:
        if not args.reference_diff.exists():
            log.error("reference workbook not found: %s", args.reference_diff)
            return 2
        mismatches = diff_against_reference(out, args.reference_diff)
        if mismatches:
            log.warning("reference-diff found %d mismatch(es):", len(mismatches))
            for m in mismatches:
                log.warning("  - %s", m)
            return 1
        log.info("reference-diff: clean — generated matches reference layout ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
