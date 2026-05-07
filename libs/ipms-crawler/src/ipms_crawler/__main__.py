"""CLI entry point for IPMS crawler.

Usage:
    # Interactive login (opens browser, scan QR with Lark)
    uv run --project libs/ipms-crawler python -m ipms_crawler login

    # Verify saved session is still valid
    uv run --project libs/ipms-crawler python -m ipms_crawler verify

    # Download BOM exports (default: 加拿大 region, 菜品 + 锅底 tabs)
    uv run --project libs/ipms-crawler python -m ipms_crawler download-bom
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ipms_crawler.auth import IPMSSession
from ipms_crawler.constants import DEFAULT_OUTPUT_DIR, DEFAULT_STORAGE_PATH
from ipms_crawler.scraper import DEFAULT_TABS, download_bom


def cmd_login(args: argparse.Namespace) -> None:
    har = Path(args.har) if args.har else None
    IPMSSession.interactive_login(
        storage_path=Path(args.storage_path),
        timeout_s=args.timeout,
        har_path=har,
        browse_after_login=args.browse,
        skip_vpn=args.skip_vpn,
    )


def cmd_verify(args: argparse.Namespace) -> None:
    try:
        with IPMSSession(
            storage_path=Path(args.storage_path),
            skip_vpn=args.skip_vpn,
        ) as session:
            print(f"✅ Session valid — URL: {session.page.url}")
    except Exception as exc:
        print(f"❌ Session invalid: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_download_bom(args: argparse.Namespace) -> None:
    tabs = tuple(args.tabs) if args.tabs else DEFAULT_TABS
    paths = download_bom(
        output_dir=Path(args.output_dir),
        tabs=tabs,
        region=args.region,
        headless=args.headless,
        skip_vpn=args.skip_vpn,
    )
    print("\n📦 Downloaded files:")
    for p in paths:
        print(f"  • {p}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="ipms_crawler",
        description="Haidilao IPMS web crawler — overseas BOM export",
    )
    parser.add_argument(
        "--storage-path",
        default=str(DEFAULT_STORAGE_PATH),
        help=f"Path to browser storage state JSON (default: {DEFAULT_STORAGE_PATH})",
    )
    parser.add_argument(
        "--skip-vpn",
        action="store_true",
        help="Skip the VPN auto-connect (use only if you've already verified VPN is up)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    login_parser = sub.add_parser("login", help="Interactive QR login (opens browser)")
    login_parser.add_argument(
        "--timeout", type=int, default=300,
        help="Max seconds to wait for login (default: 300)",
    )
    login_parser.add_argument(
        "--har", type=str, default=None,
        help="Record network traffic to a HAR file (for API reverse-engineering)",
    )
    login_parser.add_argument(
        "--browse", action="store_true",
        help="Keep browser open after login (HAR keeps recording)",
    )
    login_parser.set_defaults(func=cmd_login)

    # verify
    verify_parser = sub.add_parser("verify", help="Verify saved session")
    verify_parser.set_defaults(func=cmd_verify)

    # download-bom
    bom_parser = sub.add_parser(
        "download-bom",
        help="Download BOM exports for the given region (default: 加拿大, 菜品 + 锅底)",
    )
    bom_parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"Where to save downloaded files (default: {DEFAULT_OUTPUT_DIR})",
    )
    bom_parser.add_argument(
        "--region", default="加拿大",
        help="Region filter (default: 加拿大)",
    )
    bom_parser.add_argument(
        "--tabs", nargs="+", default=None,
        help=f"Tab names to export (default: {' '.join(DEFAULT_TABS)})",
    )
    bom_parser.add_argument(
        "--headless", action=argparse.BooleanOptionalAction, default=True,
        help="Run browser headlessly (default: True). Use --no-headless to debug.",
    )
    bom_parser.set_defaults(func=cmd_download_bom)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
