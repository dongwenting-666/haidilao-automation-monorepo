"""CLI entry point for POS crawler.

Usage:
    # Interactive login (opens browser, scan QR / enter SMS)
    uv run --project libs/pos-crawler python -m pos_crawler login

    # Verify saved session is still valid
    uv run --project libs/pos-crawler python -m pos_crawler verify

    # Take a screenshot of the homepage (quick test)
    uv run --project libs/pos-crawler python -m pos_crawler screenshot [output.png]

    # Download 菜品销售报表 — opens browser, scan QR, then drives the report.
    # POS uses session cookies that die on browser close, so we MUST do auth +
    # download in one process; storage_state alone won't carry through.
    uv run --project libs/pos-crawler python -m pos_crawler download-dish-sales \\
        --store 加拿大八店 --month 2026-03 \\
        --output-dir output/pos
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from pos_crawler.auth import POSSession, _is_login_page
from pos_crawler.constants import BASE_URL, DEFAULT_STORAGE_PATH
from pos_crawler.dish_sales import (
    GROUP_COLLECT_BY_COLUMN,
    GROUP_COLLECT_SUMMARY,
    download_dish_sales,
)
from pos_crawler.errors import POSError, POSTimeoutError


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


def _month_to_dates(month: str) -> tuple[str, str]:
    """``2026-03`` → (``2026-03-01``, ``2026-03-31``)."""
    if len(month) != 7 or month[4] != "-":
        raise SystemExit(f"--month must be YYYY-MM, got {month!r}")
    y, m = int(month[:4]), int(month[5:])
    first = date(y, m, 1)
    next_month = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    last = next_month - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _save_storage_with_promoted_cookies(
    context: "Any", storage_path: Path, log: logging.Logger
) -> None:
    """Save context.storage_state with session cookies promoted to 24h.

    POS sets ``_nb_ioWEgULi`` and friends as session cookies (no ``expires``)
    which Playwright drops on browser close. Promoting them to a 24h expiry
    before persisting lets the next run reuse the same session and skip the
    QR scan, as long as the POS server hasn't invalidated server-side.
    """
    try:
        state = context.storage_state()
        # Cookies missing/expired-zero ``expires`` get re-stamped 24h ahead.
        now = int(time.time())
        promoted = 0
        for c in state.get("cookies", []):
            if c.get("expires", -1) <= 0:
                c["expires"] = now + 86400
                promoted += 1
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        storage_path.write_text(json.dumps(state, ensure_ascii=False))
        log.info(
            "Saved storage_state to %s (promoted %d session cookies to 24h)",
            storage_path, promoted,
        )
    except Exception as exc:
        log.warning("Failed to save storage_state: %s", exc)


def _wait_for_login(page: "Any", timeout_s: int, log: logging.Logger) -> bool:
    """Block until the page is past the QR / login redirect. Returns True if
    already logged in (no manual interaction needed), False if a fresh QR
    scan happened.

    When the login page is shown, attempt to click the
    "海底捞 飞书授权登录" (Lark OAuth) button — this completes auth via
    existing Lark cookies on this host without requiring a QR scan.
    During the Lark OAuth redirect chain the URL briefly contains
    ``/oauth2/authorize`` (matched by ``_is_login_page``'s `/auth`
    substring), so we use the hostname being back at the POS origin as
    the "logged-in" signal once OAuth has been attempted.
    """
    from urllib.parse import urlparse

    deadline = time.monotonic() + timeout_s
    saw_qr = False
    oauth_attempted = False
    lark_consent_attempted = False
    oauth_selectors = (
        "text=海底捞 飞书授权登录",
        "text=飞书授权登录",
        "button:has-text('飞书授权')",
    )
    # Lark/Feishu OAuth consent screen — clicked once per app authorization
    # (Lark remembers consent after first click so subsequent runs skip it).
    lark_consent_selectors = (
        "button:has-text('Authorize')",
        "button:has-text('授权')",
        "button:has-text('同意')",
    )

    def _on_pos_app(url: str) -> bool:
        """True iff we're back on the POS origin with a non-login path."""
        u = urlparse(url)
        if "pos.superhi-tech.com" not in (u.hostname or ""):
            return False
        path = (u.path or "").lower()
        return not any(frag in path for frag in ("/login", "/sso"))

    tick = 0
    while time.monotonic() < deadline:
        try:
            qr_present = page.locator("text=飞书扫码登录").count() > 0
        except Exception:
            qr_present = True
        if tick % 5 == 0:
            log.info("[poll] url=%s qr=%s oauth_done=%s",
                     page.url, qr_present, oauth_attempted)
        tick += 1
        # When the login page is up and we haven't tried OAuth yet,
        # click the Lark-OAuth button to bypass the QR scan entirely.
        if qr_present and not oauth_attempted:
            for sel in oauth_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() == 0:
                        continue
                    loc.click(timeout=3000)
                    log.info("Clicked OAuth button (%s) — bypassing QR scan", sel)
                    oauth_attempted = True
                    time.sleep(2)
                    break
                except Exception:
                    continue
            else:
                # No OAuth button visible — mark attempted so we don't
                # loop the selector probe; fall through to QR-scan wait.
                oauth_attempted = True

        # If we're on the Lark consent screen, click 'Authorize' once.
        if (oauth_attempted and not lark_consent_attempted
                and "accounts.feishu.cn" in (urlparse(page.url).hostname or "")):
            for sel in lark_consent_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() == 0:
                        continue
                    loc.click(timeout=3000)
                    log.info("Clicked Lark consent (%s)", sel)
                    lark_consent_attempted = True
                    time.sleep(2)
                    break
                except Exception:
                    continue
        if qr_present:
            saw_qr = True
        # During the OAuth redirect chain (briefly on accounts.feishu.cn),
        # only treat ourselves as "logged in" once we're back on the POS
        # origin. Otherwise fall back to the original login-path check.
        ok = (_on_pos_app(page.url) if oauth_attempted
              else (not qr_present and not _is_login_page(page.url)))
        if ok:
            time.sleep(2)
            if (_on_pos_app(page.url) if oauth_attempted
                    else not _is_login_page(page.url)):
                log.info("✅ Logged in. URL=%s", page.url)
                return not saw_qr or oauth_attempted
        time.sleep(2)
    raise POSTimeoutError(f"Login not completed within {timeout_s}s")


def cmd_download_dish_sales(args: argparse.Namespace) -> None:
    """Open browser → wait for QR scan → drive the dish-sales report → save xlsx."""
    if args.month and (args.start or args.end):
        raise SystemExit("Use --month OR --start/--end, not both")
    if args.month:
        start_date, end_date = _month_to_dates(args.month)
    elif args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        raise SystemExit("Provide --month YYYY-MM, or both --start and --end")

    output_dir = Path(args.output_dir)
    storage_path = Path(args.storage_path)
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("pos_crawler.download_dish_sales")
    log.info(
        "Will download — store=%s, dates=%s→%s, output=%s",
        args.store, start_date, end_date, output_dir,
    )

    POSSession._ensure_browser()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        # Reuse saved cookies if we have a recent session — this is the
        # only way to avoid a QR scan, since POS uses session cookies.
        ctx_kwargs: dict = {}
        if storage_path.exists():
            try:
                ctx_kwargs["storage_state"] = str(storage_path)
                log.info("Reusing saved session at %s", storage_path)
            except Exception:
                pass
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        log.info("Opening %s — scan QR if prompted", BASE_URL)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        already_logged_in = _wait_for_login(page, args.login_timeout, log)
        # Persist the promoted cookies right away so a crash mid-download
        # doesn't force a re-scan.
        _save_storage_with_promoted_cookies(context, storage_path, log)

        try:
            output_path = download_dish_sales(
                page,
                start_date=start_date,
                end_date=end_date,
                store_name=args.store,
                output_dir=output_dir,
                group_collect=GROUP_COLLECT_BY_COLUMN if args.by_column else GROUP_COLLECT_SUMMARY,
            )
            print(f"\n✅ Saved {output_path}")
        finally:
            # Save again on the way out — the session may have refreshed.
            _save_storage_with_promoted_cookies(context, storage_path, log)
            try:
                context.close()
            finally:
                browser.close()


def cmd_debug_pos(args: argparse.Namespace) -> None:
    """Open browser, log in (or reuse session), navigate to the report, then
    log every same-origin XHR for N seconds while you click around manually.

    Use this when the auto-driver fails to fire the API: click 查询 yourself
    and watch the log for the URL pattern that needs to be replayed.
    """
    storage_path = Path(args.storage_path)
    log = logging.getLogger("pos_crawler.debug_pos")
    POSSession._ensure_browser()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx_kwargs: dict = {}
        if storage_path.exists():
            ctx_kwargs["storage_state"] = str(storage_path)
            log.info("Reusing saved session at %s", storage_path)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        _wait_for_login(page, args.login_timeout, log)
        _save_storage_with_promoted_cookies(context, storage_path, log)

        # Wire up XHR logging BEFORE navigating to the report — we want to
        # catch the auto-fire (if any). For POSTs, log the request body too
        # so we can learn the parameter schema for the API replay.
        def on_request(req: "Any") -> None:
            url = req.url
            if "pos.superhi-tech.com" not in url or req.resource_type != "xhr":
                return
            log.info("→ %s %s", req.method, url)
            if req.method == "POST":
                try:
                    body = req.post_data
                    if body:
                        # Truncate to 800 chars to keep log readable.
                        log.info("  body: %s", body[:800])
                except Exception:
                    pass

        page.on("request", on_request)

        if args.store:
            from pos_crawler.dish_sales import _switch_store
            page.wait_for_selector(".header-dropdown", state="visible", timeout=30_000)
            time.sleep(1)
            _switch_store(page, args.store)
            time.sleep(1)

        from pos_crawler.dish_sales import REPORT_URL as DISH_REPORT_URL
        log.info("Navigating to %s", DISH_REPORT_URL)
        page.goto(DISH_REPORT_URL, wait_until="domcontentloaded", timeout=60_000)

        log.info(
            "Browser is yours for %d seconds. Click 查询 manually and watch "
            "the log — the URL we need will appear with method=GET. Ctrl-C "
            "anytime to exit early.",
            args.idle_seconds,
        )
        try:
            time.sleep(args.idle_seconds)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            _save_storage_with_promoted_cookies(context, storage_path, log)
            context.close()
            browser.close()


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

    # download-dish-sales
    dish_parser = sub.add_parser(
        "download-dish-sales",
        help="Open browser → scan QR → drive 菜品销售报表 → save xlsx",
    )
    dish_parser.add_argument(
        "--store", required=True,
        help="Store display name as shown in the top-right dropdown (e.g. 加拿大八店)",
    )
    dish_parser.add_argument(
        "--month",
        help="Calendar month YYYY-MM (sets start/end to first/last day)",
    )
    dish_parser.add_argument(
        "--start", help="Start date YYYY-MM-DD (use with --end)",
    )
    dish_parser.add_argument(
        "--end", help="End date YYYY-MM-DD (use with --start)",
    )
    dish_parser.add_argument(
        "--output-dir", default="output/pos",
        help="Directory for the xlsx (default: output/pos)",
    )
    dish_parser.add_argument(
        "--login-timeout", type=int, default=300,
        help="Max seconds to wait for QR scan (default: 300)",
    )
    dish_parser.add_argument(
        "--by-column", action="store_true",
        help="Use 显示方式=分列 (per-day rows). Default is 汇总 (one row per "
             "dish-spec for the entire date range — what 红火台销售汇总 expects)",
    )
    dish_parser.set_defaults(func=cmd_download_dish_sales)

    # debug-pos: hands-on diagnostic — log XHRs while you click around
    debug_parser = sub.add_parser(
        "debug-pos",
        help="Reuse session, navigate to dish-sales report, log every XHR "
             "while you click 查询 manually so we can learn the URL pattern",
    )
    debug_parser.add_argument(
        "--store",
        help="Store to switch to before navigating (optional)",
    )
    debug_parser.add_argument(
        "--login-timeout", type=int, default=300,
        help="Max seconds to wait for QR scan if session is stale",
    )
    debug_parser.add_argument(
        "--idle-seconds", type=int, default=300,
        help="How long to keep the browser open for manual interaction",
    )
    debug_parser.set_defaults(func=cmd_debug_pos)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
