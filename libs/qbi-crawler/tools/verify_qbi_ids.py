"""Verify candidate QBI menuId/pageId by loading the dashboard URL and
reading whatever title/header text the iframe renders.

Usage:
    uv run --project libs/qbi-crawler python libs/qbi-crawler/tools/verify_qbi_ids.py \
        --menu-id ae1ba9ef-09ea-42f4-a0d2-a21b6d8c3a31 \
        --page-id 5fb4efa4-665f-421d-850f-ced91cbcd608

Prints the iframe's page title text + a snippet of body text.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv

from qbi_crawler import BASE_URL, QBISession


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--menu-id", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger(__name__)

    username = os.environ.get("QBI_USERNAME", "")
    password = os.environ.get("QBI_PASSWORD", "")
    if not username or not password:
        print("ERROR: Set QBI_USERNAME/QBI_PASSWORD in .env", file=sys.stderr)
        return 1

    with QBISession(username=username, password=password, headless=not args.headed) as session:
        page = session.page
        url = (
            f"{BASE_URL}/dashboard/view/pc.htm"
            f"?pageId={args.page_id}&menuId={args.menu_id}"
            "&dd_orientation=auto&productView=&__pcDevice__=true"
        )
        log.info("Loading: %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        # Wait for the dashboard iframe to render (same approach as production code)
        log.info("Waiting for iframe content to render...")
        for i in range(120):
            try:
                if page.inner_text("body").strip():
                    log.info("Body has text after %ds", i + 1)
                    break
            except Exception:
                pass
            time.sleep(1)

        time.sleep(5)  # let SPA settle

        # Print the iframe URLs and any visible header text
        for fr in page.frames:
            if "dashboard/view/pc.htm" in (fr.url or ""):
                log.info("Iframe: %s", fr.url[:140])
                try:
                    body = fr.inner_text("body")
                    print("=" * 60)
                    print(f"URL: {fr.url}")
                    print(f"Body length: {len(body)} chars")
                    print("First 500 chars of body:")
                    print(body[:500])
                    print("=" * 60)
                except Exception as e:
                    print(f"  could not read body: {e}", file=sys.stderr)

        # Save a screenshot for visual confirmation
        page.screenshot(path="qbi_verify.png", full_page=True)
        log.info("Screenshot saved to qbi_verify.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
