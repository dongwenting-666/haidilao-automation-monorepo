"""CLI entry point for inventory-check.

Usage::

    uv run --project projects/inventory-check python -m inventory_check.main \\
        --store CA8DKG --month 2026-03 --output-dir output/inventory-check

Today this only runs the Fiori stocktake step. POS and MB5B will be
wired in incrementally.
"""
from __future__ import annotations

import argparse
import logging
import sys

from inventory_check.pipeline import build_inventory_report

logger = logging.getLogger("inventory_check")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    p = argparse.ArgumentParser(prog="inventory_check")
    p.add_argument("--store", required=True, help="SAP user / store key, e.g. CA8DKG")
    p.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-03")
    p.add_argument("--output-dir", default="output/inventory-check")
    p.add_argument("--headless", action="store_true",
                   help="Run browser headless (default: headful — Fiori login is flaky)")
    p.add_argument("--with-pos", action="store_true",
                   help="Also download POS 红火台销售汇总 (subprocess — needs Lark QR scan unless session is fresh)")
    p.add_argument("--skip-fiori", action="store_true",
                   help="Skip Fiori stocktake step")
    p.add_argument("--skip-mb5b", action="store_true",
                   help="Skip MB5B download (default: runs SAP GUI — takes over the screen)")
    p.add_argument("--skip-zfi0156", action="store_true",
                   help="Skip ZFI0156 download (default: runs SAP GUI — covers prior month)")
    p.add_argument("--no-vpn", action="store_true",
                   help="Skip VPN check before MB5B/ZFI0156 (default: VPN is verified)")
    p.add_argument("--fiori-file", default=None,
                   help="Use this already-downloaded Fiori xlsx instead of re-running the crawler. "
                        "Note: the manual workbook's 盘点数量 column uses the *next* month's Fiori "
                        "stocktake (= end-of-current-month physical count). Pass that file via "
                        "--fiori-file to match the manual exactly; otherwise the current month's "
                        "Fiori (start-of-month count) is used.")
    p.add_argument("--fiori-source", choices=("archive", "entry"), default="archive",
                   help="archive (default): InvHisSet GET — only sees posted/archived counts. "
                        "entry: InvHSet POST — pulls the live in-progress 盘点录入 data. Use this "
                        "in the first few days of the month when ops is mid-count and the archive "
                        "is still empty.")
    p.add_argument("--mb5b-file", default=None,
                   help="Use this already-downloaded MB5B file instead of re-running SAP GUI")
    p.add_argument("--pos-file", default=None,
                   help="Use this already-downloaded 红火台销售汇总 xlsx instead of re-running "
                        "the POS crawler. Used in --template-file mode to refresh the POS sheet "
                        "+ Sheet3 pivot.")
    p.add_argument("--prev-report-file", default=None,
                   help="Last month's CA0X-盘点结果-YYYYMM.xlsx — used to fill 单价差异 (col 14)")
    p.add_argument("--zfi0156-file", default=None,
                   help="ZFI0156 export (raw or pre-pivoted) — used to fill 上月使用金额 + 对比")
    p.add_argument("--calc-file", default=None,
                   help="Workbook with the 计算 sheet (dish→material BOM) — fills 备注 (col 15)")
    p.add_argument("--template-file", default=None,
                   help="Previous month's full manual workbook (e.g. CA08-盘点结果-202603.xlsx). "
                        "When provided, the output is a multi-sheet workbook shaped exactly like "
                        "the manual: hand-curated sheets (计算, 分类, BI套餐, 红火台销售汇总, …) "
                        "are inherited from the template; only 本月系统单价mb5b / 上月数量zfi0156 / "
                        "上月数量需更新 / 上月盘点结果 / CA08-本月-盘点结果. are regenerated. The "
                        "report sheet uses VLOOKUP formulas (computed by Excel on open). Requires "
                        "--prev-report-file and --zfi0156-file.")
    p.add_argument("--no-assemble", action="store_true",
                   help="Skip the final 盘点结果 report assembly")

    args = p.parse_args(argv)

    artifacts = build_inventory_report(
        sap_user=args.store,
        month_str=args.month,
        out_dir=args.output_dir,
        headless=args.headless,
        skip_pos=not args.with_pos,
        skip_fiori=args.skip_fiori,
        skip_mb5b=args.skip_mb5b,
        skip_zfi0156=args.skip_zfi0156,
        skip_vpn=args.no_vpn,
        fiori_path=args.fiori_file,
        fiori_use_entry=(args.fiori_source == "entry"),
        mb5b_path=args.mb5b_file,
        pos_path=args.pos_file,
        prev_report_path=args.prev_report_file,
        zfi0156_path=args.zfi0156_file,
        calc_path=args.calc_file,
        template_path=args.template_file,
        assemble=not args.no_assemble,
    )

    print("\n=== artifacts ===")
    print(f"fiori_stocktake: {artifacts.fiori_stocktake or '— skipped'}")
    print(f"pos_dish_sales:  {artifacts.pos_dish_sales or '— skipped'}")
    print(f"mb5b:            {artifacts.mb5b or '— skipped'}")
    print(f"zfi0156:         {artifacts.zfi0156 or '— skipped'}")
    print(f"report:          {artifacts.report or '— not assembled'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
