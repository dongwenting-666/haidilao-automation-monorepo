"""High-level orchestration: download sources + assemble 盘点结果.

v1 scope (CA08-only)
--------------------
- Stocktake counts: SAP Fiori 盘点报表 (sap-fiori-crawler).
- System inventory + monthly movements: SAP MB5B (sap-gui — desktop SAP
  GUI automation, takes over the screen).
- POS sales summary: 红火台销售汇总 (pos-crawler).

Out of scope (v1):
- BOM / 折算数量 / 对照表 / 分类 (static reference tables — drop-in)
- Final 盘点结果 derivation that combines all of the above

Each downloader can be skipped independently so partial runs are easy
to debug, and so a re-run can pick up where a step failed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sap_fiori_crawler import (
    download_stocktake_entry,
    download_stocktake_report,
    fiori_session,
    load_store_creds,
)

from inventory_check.dates import Month, parse_month
from inventory_check.stores import Store, get_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryArtifacts:
    """Where each downloaded source landed on disk."""

    fiori_stocktake: Path | None
    pos_dish_sales: Path | None
    mb5b: Path | None
    zfi0156: Path | None = None
    report: Path | None = None


def download_fiori_stocktake(
    store: Store,
    month: Month,
    out_dir: Path,
    *,
    headless: bool = False,
    use_entry: bool = False,
) -> Path:
    """Download Fiori 盘点报表 (or 盘点录入) for one store/month.

    Two source paths:

    - ``use_entry=False`` (default): InvHisSet OData GET — returns the
      *archived* count for the given period. Empty when this month's
      count hasn't been posted/archived yet.
    - ``use_entry=True``: InvHSet POST (deep-create envelope) — returns
      the *in-progress* count from the 盘点录入 app's local model.
      Use this in early month-end windows when ops is mid-count and
      InvHisSet hasn't archived yet.

    The schemas differ slightly (entry path lacks Pici/Zdate/Ztime and
    uses Status as a numeric code), but the file produced by either
    path is consumable by ``report._read_fiori_count_by_matnr``.
    """
    creds = load_store_creds(store.sap_user)
    src = "盘点录入 (live)" if use_entry else "盘点报表 (archive)"
    logger.info(
        "fiori %s → store=%s month=%s out=%s headless=%s",
        src, store.sap_user, month.period, out_dir, headless,
    )
    with fiori_session(creds, headless=headless) as (browser, ctx, page):
        del browser, page
        if use_entry:
            return download_stocktake_entry(
                ctx, user=store.sap_user, period=month.period, out_dir=out_dir,
            )
        return download_stocktake_report(
            ctx, year=month.year, month=month.month, user=store.sap_user, out_dir=out_dir
        )


def download_pos_dish_sales(
    store: Store,
    month: Month,
    out_dir: Path,
    *,
    login_timeout_s: int = 300,
) -> Path:
    """Run pos_crawler download-dish-sales as a subprocess.

    POS is interactive (Lark QR scan unless a recent session cookie is
    cached), so we shell out to the existing CLI rather than reach into
    its private session helpers. The subprocess inherits stdin/stdout so
    the QR prompt is visible.
    """
    import subprocess
    import sys

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pos_crawler", "download-dish-sales",
        "--store", store.pos_name,
        "--month", f"{month.year:04d}-{month.month:02d}",
        "--output-dir", str(out_dir),
        "--login-timeout", str(login_timeout_s),
    ]
    logger.info("POS dish-sales subprocess: %s", " ".join(cmd))
    completed = subprocess.run(cmd, check=True)
    del completed

    # Match the filename pos_crawler writes: ``{store}-菜品销售汇总-YYYYMMDD-YYYYMMDD.xlsx``.
    name = (
        f"{store.pos_name}-菜品销售汇总-"
        f"{month.year:04d}{month.month:02d}01-"
        f"{month.year:04d}{month.month:02d}{_last_day_of(month):02d}.xlsx"
    )
    expected = out_dir / name
    if not expected.exists():
        # Fall back to whatever xlsx is newest in out_dir matching the prefix.
        candidates = sorted(
            out_dir.glob(f"{store.pos_name}-菜品销售汇总-*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            expected = candidates[0]
            logger.info("POS produced %s (didn't match expected name)", expected)
        else:
            raise RuntimeError(
                f"POS subprocess succeeded but no xlsx found in {out_dir}"
            )
    return expected


def _last_day_of(month: Month) -> int:
    from calendar import monthrange

    return monthrange(month.year, month.month)[1]


def download_zfi0156(
    store: Store,
    month: Month,
    out_dir: Path,
    *,
    plant_low: str = "CA01",
    plant_high: str = "CA09",
    skip_vpn: bool = False,
) -> Path:
    """Download ZFI0156 (门店实际耗用数据统计表) for the *previous* month.

    The inventory report for month M uses ZFI0156 covering M-1 to fill
    the 上月使用金额 / 上月使用数量 columns. This helper computes that
    date range automatically.

    Like MB5B, this takes over the screen via SAP GUI desktop. Region-wide
    plant range by default (CA01-CA09); the inventory pipeline filters
    to the store's werks downstream.
    """
    from datetime import date

    from sap_gui.processes.zfi0156 import default_filename, run as zfi_run

    username = os.environ.get("SAP_USERNAME")
    password = os.environ.get("SAP_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "SAP_USERNAME and SAP_PASSWORD must be set in environment / .env"
        )

    if not skip_vpn:
        from vpn import ensure_vpn

        logger.info("ensuring VPN…")
        ensure_vpn()

    # Previous month relative to the inventory report month.
    first_of_inv = date(month.year, month.month, 1)
    from datetime import timedelta
    last_of_prev = first_of_inv - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    output = Path(out_dir) / default_filename(first_of_prev)

    logger.info(
        "ZFI0156 → store=%s (plants %s-%s) %s..%s out=%s",
        store.werks, plant_low, plant_high, first_of_prev, last_of_prev, output,
    )
    return zfi_run(
        username=username,
        password=password,
        output_path=output,
        plant_low=plant_low,
        plant_high=plant_high,
        date_from=first_of_prev,
        date_to=last_of_prev,
    )


def download_mb5b(
    store: Store,
    month: Month,
    out_dir: Path,
    *,
    company_low: str = "9451",
    company_high: str = "9452",
    skip_vpn: bool = False,
) -> Path:
    """Download MB5B (System -> List -> Save -> Local File -> Spreadsheet).

    Uses the SAP GUI desktop transaction via ``sap_gui.processes.mb5b``.
    Output is UTF-16 LE TSV with .xls extension — see
    ``inventory_check.mb5b_parse`` to read it.

    SAP GUI takes over the screen during this run. Don't call from
    background jobs that the user might be using interactively.
    """
    from datetime import date

    from sap_gui.processes.mb5b import default_filename, run as mb5b_run

    username = os.environ.get("SAP_USERNAME")
    password = os.environ.get("SAP_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "SAP_USERNAME and SAP_PASSWORD must be set in environment / .env"
        )

    if not skip_vpn:
        from vpn import ensure_vpn

        logger.info("ensuring VPN…")
        ensure_vpn()

    d_from = date(month.year, month.month, 1)
    from calendar import monthrange
    last_day = monthrange(month.year, month.month)[1]
    d_to = date(month.year, month.month, last_day)
    output = Path(out_dir) / default_filename(d_from)

    logger.info(
        "MB5B → store=%s (BUKRS %s-%s) %s..%s out=%s",
        store.werks, company_low, company_high, d_from, d_to, output,
    )
    return mb5b_run(
        username=username,
        password=password,
        output_path=output,
        company_low=company_low,
        company_high=company_high,
        date_from=d_from,
        date_to=d_to,
    )


def build_inventory_report(
    sap_user: str,
    month_str: str,
    out_dir: str | Path,
    *,
    headless: bool = False,
    skip_pos: bool = True,
    skip_fiori: bool = False,
    skip_mb5b: bool = False,
    skip_zfi0156: bool = False,
    skip_vpn: bool = False,
    fiori_path: Path | str | None = None,
    fiori_use_entry: bool = False,
    mb5b_path: Path | str | None = None,
    pos_path: Path | str | None = None,
    pos_set_path: Path | str | None = None,
    prev_report_path: Path | str | None = None,
    zfi0156_path: Path | str | None = None,
    calc_path: Path | str | None = None,
    template_path: Path | str | None = None,
    assemble: bool = True,
) -> InventoryArtifacts:
    """End-to-end orchestration entry point.

    Each step runs only if its ``skip_*`` flag is False. Defaults skip the
    interactive-only steps (POS QR scan, SAP GUI screen takeover) so a
    plain call only runs the Fiori OData replay.

    ``fiori_path`` / ``mb5b_path`` let you point at already-downloaded
    files instead of re-running the crawler — handy for iterating on
    report assembly logic.
    """
    store = get_store(sap_user)
    month = parse_month(month_str)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fiori_resolved: Path | None = Path(fiori_path) if fiori_path else None
    if fiori_resolved is None and not skip_fiori:
        fiori_resolved = download_fiori_stocktake(
            store, month, out_dir, headless=headless, use_entry=fiori_use_entry,
        )
    elif fiori_resolved is not None:
        logger.info("Fiori stocktake: using existing %s", fiori_resolved)
    else:
        logger.info("Fiori stocktake: skipped (--skip-fiori)")

    pos_resolved: Path | None = Path(pos_path) if pos_path else None
    if pos_resolved is None and not skip_pos:
        pos_resolved = download_pos_dish_sales(store, month, out_dir)
    elif pos_resolved is not None:
        logger.info("POS dish-sales: using existing %s", pos_resolved)
    else:
        logger.info("POS dish-sales: skipped (--with-pos not set) — opt-in due to QR scan")

    mb5b_resolved: Path | None = Path(mb5b_path) if mb5b_path else None
    if mb5b_resolved is None and not skip_mb5b:
        mb5b_resolved = download_mb5b(store, month, out_dir, skip_vpn=skip_vpn)
    elif mb5b_resolved is not None:
        logger.info("MB5B: using existing %s", mb5b_resolved)
    else:
        logger.info("MB5B: skipped (--skip-mb5b)")

    zfi0156_resolved: Path | None = Path(zfi0156_path) if zfi0156_path else None
    if zfi0156_resolved is None and not skip_zfi0156:
        zfi0156_resolved = download_zfi0156(store, month, out_dir, skip_vpn=skip_vpn)
    elif zfi0156_resolved is not None:
        logger.info("ZFI0156: using existing %s", zfi0156_resolved)
    else:
        logger.info("ZFI0156: skipped (--skip-zfi0156)")

    report_path: Path | None = None
    if assemble and fiori_resolved is not None and mb5b_resolved is not None:
        if template_path:
            # Multi-sheet workbook mode — produce a file shaped exactly
            # like the manual workbook by reusing the prior month's
            # template and swapping the data sheets.
            from inventory_check.workbook import (
                WorkbookSources,
                assemble_workbook,
            )

            file_name = f"{store.werks}-盘点结果-{month.period}.xlsx"
            report_path = assemble_workbook(
                WorkbookSources(
                    template_path=Path(template_path),
                    mb5b_path=mb5b_resolved,
                    fiori_path=fiori_resolved,
                    zfi0156_path=zfi0156_resolved,
                    prev_report_path=(
                        Path(prev_report_path) if prev_report_path else None
                    ),
                    pos_path=pos_resolved,
                    pos_set_path=Path(pos_set_path) if pos_set_path else None,
                ),
                store=store, month=month,
                out_path=out_dir / file_name,
            )
        else:
            from inventory_check.report import assemble_report

            report_path = assemble_report(
                store=store, month=month,
                mb5b_path=mb5b_resolved, fiori_path=fiori_resolved,
                prev_report_path=Path(prev_report_path) if prev_report_path else None,
                zfi0156_path=zfi0156_resolved,
                calc_path=Path(calc_path) if calc_path else None,
                out_dir=out_dir,
            )
    elif assemble:
        logger.info(
            "Report assembly: skipped — need both Fiori (%s) and MB5B (%s)",
            fiori_resolved, mb5b_resolved,
        )

    return InventoryArtifacts(
        fiori_stocktake=fiori_resolved,
        pos_dish_sales=pos_resolved,
        mb5b=mb5b_resolved,
        zfi0156=zfi0156_resolved,
        report=report_path,
    )
