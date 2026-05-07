"""CLI for SAP Fiori crawler.

Usage::

    # Download stocktake report for one store + month
    uv run --project libs/sap-fiori-crawler python -m sap_fiori_crawler \\
        download-stocktake --store CA8DKG --month 2026-03 \\
        --output-dir output/fiori

    # Headless (default is headful because login is flaky)
    uv run --project libs/sap-fiori-crawler python -m sap_fiori_crawler \\
        download-stocktake --store CA8DKG --month 2026-03 --headless

Credentials are read from ``$SGPFIORIWEB_CREDS`` (JSON dict
mapping store-key → password). Loads .env from the working directory if present.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sap_fiori_crawler.auth import StoreCreds, fiori_session, load_store_creds
from sap_fiori_crawler.errors import FioriError
from sap_fiori_crawler.stocktake import download_stocktake_report


logger = logging.getLogger("sap_fiori_crawler")


def _parse_month(month: str) -> tuple[int, int]:
    if len(month) != 7 or month[4] != "-":
        raise SystemExit(f"--month must be YYYY-MM, got {month!r}")
    try:
        y, m = int(month[:4]), int(month[5:])
    except ValueError as exc:
        raise SystemExit(f"--month must be YYYY-MM, got {month!r}") from exc
    if not 1 <= m <= 12:
        raise SystemExit(f"month must be 1-12, got {m}")
    return y, m


def cmd_download_stocktake(args: argparse.Namespace) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()  # picks up .env from CWD if present
    except ImportError:
        pass

    year, month = _parse_month(args.month)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        creds = load_store_creds(args.store)
    except FioriError as exc:
        logger.error("credentials lookup failed: %s", exc)
        return 2

    if args.password:
        creds = StoreCreds(user=args.store, password=args.password, client=creds.client)

    logger.info(
        "downloading stocktake for store=%s year=%d month=%d → %s (headless=%s)",
        args.store, year, month, out_dir, args.headless,
    )

    try:
        with fiori_session(creds, headless=args.headless) as (browser, ctx, page):
            del browser, page  # not needed; OData replay uses ctx.request only
            out = download_stocktake_report(
                ctx, year=year, month=month, user=args.store, out_dir=out_dir
            )
    except FioriError as exc:
        logger.error("download failed: %s", exc)
        return 1

    print(f"📦 saved {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser(prog="sap_fiori_crawler")
    sub = p.add_subparsers(dest="cmd", required=True)

    dl = sub.add_parser("download-stocktake", help="Download 盘点报表 for one store + month.")
    dl.add_argument("--store", required=True, help="SAP user / store key, e.g. CA8DKG")
    dl.add_argument("--month", required=True, help="YYYY-MM")
    dl.add_argument("--output-dir", default="output/fiori")
    dl.add_argument("--headless", action="store_true", help="Run headless (default: headful)")
    dl.add_argument(
        "--password",
        default=None,
        help="Override password (default: read from SGPFIORIWEB_CREDS)",
    )
    dl.set_defaults(func=cmd_download_stocktake)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
