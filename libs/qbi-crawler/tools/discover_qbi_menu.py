"""Discover QBI menuId/pageId for a sidebar leaf.

The QBI portal sidebar uses ``.menu-item.level-1`` (sections) and
``.menu-item.level-2`` (leaves), with ``.menu-item-collapse`` /
``.menu-item-expand`` for collapsed-vs-expanded state.

Lessons from the 2026-04-29 discovery session (worth repeating here so
the next person doesn't repeat them):

1. Sidebar tree state is per-session — sections may be collapsed by
   default in headless even if expanded in your headed browser.
2. ``get_by_text(exact=True)`` matches breadcrumbs and tooltips too —
   always scope to ``.menu-item.level-N`` to avoid false positives.
3. Clicking a collapsed section navigates to its currently-selected
   child as a side-effect (URL changes in the dashboard iframe).
4. JS ``.click()`` updates React's CSS state (``menu-item-selected``)
   but does NOT trigger React's routing — you need a real CDP-driven
   mouse click (Playwright's ``locator.click()``) for that.
5. The leaf-click → dashboard-iframe-URL-change can take **>60s** —
   wire up a ``framenavigated`` listener BEFORE clicking and budget
   at least 120s.
6. Always run ``verify_qbi_ids.py`` on the captured pageId/menuId —
   the discovered URL may be the section default, not the leaf you
   wanted. The verifier loads the URL and prints the body's title text.

Usage:
    uv run --project libs/qbi-crawler python libs/qbi-crawler/tools/discover_qbi_menu.py \
        --tab 菜品专题 --section 菜品销售 --leaf 海外套餐销售明细
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from qbi_crawler import BASE_URL, QBISession


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tab", required=True)
    parser.add_argument("--section", required=True)
    parser.add_argument("--leaf", required=True)
    parser.add_argument("--report-name", default="REPORT_OVERSEAS_SET_MEAL")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger(__name__)

    username = os.environ.get("QBI_USERNAME", "")
    password = os.environ.get("QBI_PASSWORD", "")
    if not username or not password:
        print("ERROR: creds missing", file=sys.stderr)
        return 1

    with QBISession(username=username, password=password, headless=not args.headed) as session:
        page = session.page
        page.goto(f"{BASE_URL}/view/portal", wait_until="domcontentloaded", timeout=120_000)

        log.info("Waiting for portal SPA + tab text...")
        for _ in range(120):
            try:
                for fr in page.frames:
                    if fr.locator(f':text("{args.tab}")').count() > 0:
                        raise StopIteration
            except StopIteration:
                break
            except Exception:
                pass
            time.sleep(1)
        time.sleep(2)

        log.info("Clicking tab %r", args.tab)
        for fr in page.frames:
            try:
                loc = fr.locator(f':text("{args.tab}")').first
                if loc.count() > 0:
                    loc.click(timeout=10_000)
                    log.info("  clicked in %s", fr.url[:60])
                    break
            except Exception:
                pass
        time.sleep(5)

        # Find the workspace iframe (where the sidebar lives)
        ws = next((f for f in page.frames if "product/view.htm" in (f.url or "")), None)
        if ws is None:
            print("ERROR: workspace iframe not found", file=sys.stderr)
            return 2

        # Helper JS: find a .menu-item with exact title text matching `name`
        # and either click it or read its data — avoids matching breadcrumbs.
        find_menu_js = """
            ({name, level}) => {
                const sel = level === 1 ? '.menu-item.level-1' : '.menu-item.level-2';
                const all = document.querySelectorAll(sel);
                for (const el of all) {
                    const title = el.querySelector('.menu-item-title');
                    if (title && title.textContent.trim() === name) {
                        // Mark it so Playwright can click via a stable selector
                        el.setAttribute('data-qbi-pick', '1');
                        return {
                            found: true,
                            classes: el.className,
                            html: el.outerHTML.slice(0, 600),
                        };
                    }
                }
                return {found: false};
            }
        """

        log.info("Locating section %r as level-1 menu item...", args.section)
        sec_info = ws.evaluate(find_menu_js, {"name": args.section, "level": 1})
        if not sec_info["found"]:
            print(f"ERROR: section {args.section!r} not found as .menu-item.level-1", file=sys.stderr)
            return 3
        log.info("  section classes: %s", sec_info["classes"])

        # Click only if collapsed (no menu-item-expand class)
        if "menu-item-expand" not in sec_info["classes"]:
            log.info("Section is COLLAPSED — clicking to expand")
            ws.locator('.menu-item.level-1[data-qbi-pick="1"]').first.click(timeout=10_000)
            time.sleep(2)
        else:
            log.info("Section is already EXPANDED — skipping click")

        # Now find the leaf
        log.info("Locating leaf %r as level-2 menu item...", args.leaf)
        for attempt in range(10):
            leaf_info = ws.evaluate(find_menu_js, {"name": args.leaf, "level": 2})
            if leaf_info["found"]:
                break
            time.sleep(1)
        else:
            print(f"ERROR: leaf {args.leaf!r} not found as .menu-item.level-2", file=sys.stderr)
            return 4
        log.info("  leaf classes: %s", leaf_info["classes"])
        log.info("  leaf html sample: %s", leaf_info["html"][:300])

        # Snapshot the dashboard iframe URL BEFORE clicking the leaf
        url_before = next(
            (f.url for f in page.frames if "dashboard/view/pc.htm" in (f.url or "")),
            "",
        )
        log.info("Dashboard iframe BEFORE: %s", (url_before or "(none)")[:140])

        # Wire up a navigation-listener BEFORE clicking — React's synthetic
        # event system might fire after a delay, and polling can miss the
        # transition if Playwright sees the old URL across multiple ticks.
        captured_urls: list[str] = []

        def _on_frame_navigated(fr):
            u = fr.url or ""
            if "dashboard/view/pc.htm" in u and u != url_before:
                captured_urls.append(u)
                log.info("framenavigated -> %s", u[:140])

        page.on("framenavigated", _on_frame_navigated)

        # Click via Playwright's CDP-driven mouse click on .menu-item-inner.
        # JS .click() fires native DOM events but React listens for synthetic
        # events at the document level and doesn't always catch them. A real
        # mouse event via Playwright DOES trigger React's handler.
        log.info("Clicking leaf via Playwright CDP click on .menu-item-inner...")
        ws.evaluate("""
            () => {
                document.querySelectorAll('[data-qbi-pick]').forEach(el => el.removeAttribute('data-qbi-pick'));
            }
        """)
        ws.evaluate(find_menu_js, {"name": args.leaf, "level": 2})
        # Click the deeper .menu-item-inner element (the actual click handler target)
        inner_loc = ws.locator('.menu-item.level-2[data-qbi-pick="1"] .menu-item-inner').first
        if inner_loc.count() == 0:
            inner_loc = ws.locator('.menu-item.level-2[data-qbi-pick="1"]').first
        inner_loc.scroll_into_view_if_needed(timeout=5_000)
        inner_loc.click(timeout=10_000)

        log.info("Waiting for dashboard iframe URL to change (up to 120s)...")
        target_url = ""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            elapsed = int(120 - (deadline - time.monotonic()))
            if elapsed and elapsed % 15 == 0:
                log.info("  ...%ds elapsed, current frames:", elapsed)
                for fr in page.frames:
                    if "dashboard/view/pc.htm" in (fr.url or ""):
                        log.info("    %s", fr.url[:140])
            if captured_urls:
                target_url = captured_urls[-1]
                break
            for frame in page.frames:
                u = frame.url or ""
                if "dashboard/view/pc.htm" in u and u != url_before:
                    target_url = u
                    break
            if target_url:
                break
            time.sleep(2)

        if not target_url:
            page.screenshot(path="qbi_v2_debug.png", full_page=True)
            print("ERROR: dashboard iframe URL never changed", file=sys.stderr)
            print(f"BEFORE: {url_before}", file=sys.stderr)
            for fr in page.frames:
                print(f"  frame: {fr.url}", file=sys.stderr)
            return 5

        params = parse_qs(urlparse(target_url).query)
        page_id = (params.get("pageId") or [""])[0]
        menu_id = (params.get("menuId") or [""])[0]

        print("=" * 70)
        print(f"Leaf:    {args.leaf}")
        print(f"menuId:  {menu_id}")
        print(f"pageId:  {page_id}")
        print(f"URL:     {target_url}")
        print("=" * 70)
        print()
        print("Add to dashboard.py:")
        print(f'    {args.report_name}: "{menu_id}",   # in _REPORT_MENU_IDS')
        print(f'    {args.report_name}: "{page_id}",   # in _REPORT_PAGE_IDS')
    return 0


if __name__ == "__main__":
    sys.exit(main())
