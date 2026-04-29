"""CLI entry point for POS crawler.

Usage:
    # Interactive login (opens browser, scan QR / enter SMS)
    uv run --project libs/pos-crawler python -m pos_crawler login

    # Verify saved session is still valid
    uv run --project libs/pos-crawler python -m pos_crawler verify

    # Take a screenshot of the homepage (quick test)
    uv run --project libs/pos-crawler python -m pos_crawler screenshot [output.png]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pos_crawler.auth import POSSession
from pos_crawler.constants import DEFAULT_STORAGE_PATH


def cmd_login(args: argparse.Namespace) -> None:
    """Run interactive login in a visible browser."""
    har = Path(args.har) if args.har else None
    POSSession.interactive_login(
        storage_path=Path(args.storage_path),
        timeout_s=args.timeout,
        har_path=har,
        browse_after_login=args.browse,
    )


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify the saved session is still valid."""
    try:
        with POSSession(storage_path=Path(args.storage_path)) as session:
            print(f"✅ Session valid — URL: {session.page.url}")
    except Exception as exc:
        print(f"❌ Session invalid: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_screenshot(args: argparse.Namespace) -> None:
    """Take a screenshot of the POS homepage."""
    output = Path(args.output)
    with POSSession(storage_path=Path(args.storage_path)) as session:
        session.screenshot(output)
        print(f"📸 Screenshot saved to {output}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="pos_crawler",
        description="Haidilao POS web crawler",
    )
    parser.add_argument(
        "--storage-path",
        default=str(DEFAULT_STORAGE_PATH),
        help=f"Path to browser storage state JSON (default: {DEFAULT_STORAGE_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    login_parser = sub.add_parser("login", help="Interactive login (opens browser)")
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
        help="Keep browser open after login so you can click around (HAR keeps recording)",
    )
    login_parser.set_defaults(func=cmd_login)

    # verify
    verify_parser = sub.add_parser("verify", help="Verify saved session")
    verify_parser.set_defaults(func=cmd_verify)

    # screenshot
    ss_parser = sub.add_parser("screenshot", help="Screenshot POS homepage")
    ss_parser.add_argument("output", nargs="?", default="pos_screenshot.png")
    ss_parser.set_defaults(func=cmd_screenshot)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
