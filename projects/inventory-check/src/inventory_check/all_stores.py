"""Multi-store 盘点结果 generator — single browser session, single MB5B/ZFI.

Logs in to POS *once* (preferring CDP attach to a running Chrome with
`scripts/start-chrome-cdp.sh` so silent OAuth via 飞书授权登录 grants
without a QR scan), then downloads the POS sheet for every store back-
to-back. The shared MB5B and ZFI0156 files are expected to already be
on disk under ``<output-root>/<period>/`` (run the single-store
``inventory_check.main`` once or download them manually first — they
cover the whole region so re-running per store is wasted work).

For each store, calls the regular pipeline with all per-source paths
pinned (skip_pos/skip_fiori/skip_mb5b/skip_zfi0156 = True) so the only
work is workbook assembly. The Fiori 盘点录入 (POST /InvHSet — entry
mode) is downloaded per-store from the *next* month, since that is
where the end-of-current-month physical count lives.

Run::

    uv run --project projects/inventory-check python -m \\
        inventory_check.all_stores --month 2026-04 \\
        --template ~/Downloads/CA08-盘点结果-202603.xlsx

Skips stores listed in ``--skip`` (comma-separated). The default skip
list reflects long-known issues: CA03 has no Fiori 盘点录入 entry, and
CA05's Fiori login fails. Override with ``--skip ""`` to attempt
everyone, or pass an explicit list.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from inventory_check.dates import Month, parse_month
from inventory_check.pipeline import (
    build_inventory_report,
    download_fiori_stocktake,
)
from inventory_check.stores import get_store

logger = logging.getLogger("inventory_check.all_stores")

ALL_STORES = ["CA1DKG", "CA2DKG", "CA3DKG", "CA4DKG",
              "CA5DKG", "CA6DKG", "CA7DKG", "CA8DKG"]
DEFAULT_SKIP = ["CA3DKG", "CA5DKG"]
CDP_URL = "http://localhost:9222"
LOGIN_TIMEOUT_S = 600


def _next_month(m: Month) -> Month:
    if m.month == 12:
        return Month(m.year + 1, 1)
    return Month(m.year, m.month + 1)


def _prev_month(m: Month) -> Month:
    if m.month == 1:
        return Month(m.year - 1, 12)
    return Month(m.year, m.month - 1)


def _click_authorize_in_popup(p) -> bool:
    """Click the OAuth Authorize/授权 button (skip Reject/拒绝)."""
    try:
        for label in ("Authorize", "授权"):
            loc = p.locator(f"button:has-text('{label}')")
            for i in range(loc.count()):
                btn = loc.nth(i)
                txt = (btn.inner_text() or "").strip()
                if "Reject" in txt or "拒绝" in txt:
                    continue
                if txt in ("Authorize", "授权"):
                    btn.click()
                    return True
    except Exception:
        pass
    return False


def _click_authorize_button(page, context) -> None:
    """Click 飞书授权登录, then auto-grant on the Feishu confirm screen.

    After the click, the page (or a popup) navigates to
    `accounts.feishu.cn/.../authorize`. We click `Authorize`/`授权`
    on whichever surface holds it — Feishu then redirects back to POS
    with `?code=…&state=success_login#/loginTemp`. The caller's wait
    loop handles the post-redirect `/loginTemp` consume retries.
    """
    try:
        btn = page.locator("text=飞书授权登录").first
        if btn.count() == 0:
            return
        logger.info("clicking '飞书授权登录' (try silent OAuth)")
        popups: list = []
        context.on("page", lambda p: popups.append(p))
        btn.click()
        page.wait_for_timeout(5_000)
        for p in [page] + popups:
            try:
                url = p.url or ""
            except Exception:
                continue
            if "feishu.cn" not in url or "authorize" not in url:
                continue
            try:
                p.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            if _click_authorize_in_popup(p):
                logger.info("  ✓ auto-clicked Authorize on %s", url[:80])
    except Exception as exc:
        logger.warning("authorize click failed: %s", exc)


def _wait_for_login(page, context, timeout_s: int) -> None:
    """Block until POS is fully logged in.

    After silent OAuth, POS lands at ``?code=…&state=success_login#/loginTemp``
    where the SPA is supposed to exchange the code for a session token.
    Under Playwright/CDP the exchange sometimes doesn't fire on first
    mount — page.reload() with the URL fragment intact re-runs the SPA
    mount lifecycle and triggers the exchange. We retry the reload up to
    ``LOGIN_TEMP_RELOAD_ATTEMPTS`` times before giving up to QR fallback.
    """
    LOGIN_TEMP_RELOAD_ATTEMPTS = 3
    LOGIN_TEMP_RELOAD_INTERVAL_S = 8

    deadline = time.monotonic() + timeout_s
    last_prompt = 0.0
    clicked_authorize = False
    reload_count = 0
    next_reload_at = 0.0

    while time.monotonic() < deadline:
        try:
            ready = page.locator(".header-dropdown").count() > 0
        except Exception:
            ready = False
        if ready:
            logger.info("✅ POS logged in. URL=%s", page.url)
            return

        try:
            url = page.url or ""
        except Exception:
            url = ""

        # SPA parked at /loginTemp — reload (preserving the OAuth code in
        # URL) until the SPA finally consumes it.
        if ("loginTemp" in url and clicked_authorize
                and reload_count < LOGIN_TEMP_RELOAD_ATTEMPTS
                and time.monotonic() >= next_reload_at):
            reload_count += 1
            logger.info(
                "/loginTemp not consumed yet — reload %d/%d (URL preserved)",
                reload_count, LOGIN_TEMP_RELOAD_ATTEMPTS,
            )
            try:
                page.reload(wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(3_000)
            except Exception as exc:
                logger.warning("reload failed: %s", exc)
            next_reload_at = time.monotonic() + LOGIN_TEMP_RELOAD_INTERVAL_S
            continue

        if not clicked_authorize:
            try:
                if page.locator("text=飞书授权登录").count() > 0:
                    _click_authorize_button(page, context)
                    clicked_authorize = True
                    page.wait_for_timeout(2_000)
                    continue
            except Exception:
                pass

        try:
            qr = page.locator("text=飞书扫码登录").count() > 0
        except Exception:
            qr = False
        if qr:
            now = time.monotonic()
            if now - last_prompt > 10:
                logger.warning(">>> SCAN QR (silent OAuth didn't grant) — %ds left <<<",
                               int(deadline - now))
                last_prompt = now
        time.sleep(2)
    raise RuntimeError(
        f"POS login not completed within {timeout_s}s. URL: {page.url}"
    )


def _try_connect_cdp(pw):
    """Attach to Chrome started by ``scripts/start-chrome-cdp.sh``."""
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2).read()
    except Exception:
        return None
    logger.info("CDP live at %s — attaching", CDP_URL)
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    contexts = browser.contexts
    ctx = contexts[0] if contexts else browser.new_context()
    return browser, ctx, False


def download_pos_for_all(stores: list[str], month: Month,
                         out_root: Path,
                         ) -> tuple[dict[str, Path | None], dict[str, Path | None]]:
    """Single-session POS sweep — log in once, switch dropdown per store.

    Returns (dish_sales_paths, set_sales_paths) keyed by store_key. Both
    reports come from the same logged-in session; if the second download
    fails (e.g., listDishSetSale not exposed for this account) we still
    return the dish_sales path so the inventory-check workbook can build
    with W=0.
    """
    from playwright.sync_api import sync_playwright

    from pos_crawler.auth import POSSession
    from pos_crawler.constants import BASE_URL, DEFAULT_STORAGE_PATH
    from pos_crawler.dish_sales import download_dish_sales
    from pos_crawler.dish_set_sales import download_dish_set_sales

    POSSession._ensure_browser()
    results: dict[str, Path | None] = {}
    set_results: dict[str, Path | None] = {}
    storage_path = Path(DEFAULT_STORAGE_PATH)

    with sync_playwright() as pw:
        cdp = _try_connect_cdp(pw)
        if cdp:
            browser, context, owns_browser = cdp
        else:
            logger.info(
                "No CDP at %s — launching isolated Chromium "
                "(start scripts/start-chrome-cdp.sh once for the no-QR path)",
                CDP_URL,
            )
            browser = pw.chromium.launch(headless=False)
            ctx_kwargs: dict = {}
            if storage_path.exists():
                ctx_kwargs["storage_state"] = str(storage_path)
            context = browser.new_context(**ctx_kwargs)
            owns_browser = True

        page = None
        if not owns_browser:
            for p in context.pages:
                try:
                    if "pos.superhi-tech.com" in p.url:
                        page = p
                        page.bring_to_front()
                        logger.info("reusing POS tab: %s", p.url)
                        break
                except Exception:
                    pass
        if page is None:
            page = context.new_page()
            try:
                page.goto(BASE_URL, wait_until="commit", timeout=15_000)
            except Exception as exc:
                logger.warning("goto raised %s — continuing", exc)
        page.wait_for_timeout(3_000)

        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to set frontmost of '
                 'first process whose name contains "Chrom" to true'],
                check=False, timeout=5,
            )
        except Exception:
            pass

        _wait_for_login(page, context, LOGIN_TIMEOUT_S)
        try:
            context.storage_state(path=str(storage_path))
        except Exception:
            pass

        for store_key in stores:
            store = get_store(store_key)
            out_dir = out_root / store.werks
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                logger.info("[%s] POS download (store=%s)", store_key, store.pos_name)
                pos_path = download_dish_sales(
                    page,
                    start_date=month.first_day_iso,
                    end_date=month.last_day_iso,
                    store_name=store.pos_name,
                    output_dir=out_dir,
                )
                results[store_key] = pos_path
                logger.info("[%s] POS → %s", store_key, pos_path)
            except Exception:
                logger.exception("[%s] POS download failed", store_key)
                results[store_key] = None

            # Set-meal breakdown (BI套餐 source). Independent failure mode:
            # if listDishSetSale isn't exposed or returns 0 rows we fall
            # back to W=0 in the calc sheet — non-fatal.
            try:
                logger.info("[%s] POS set-sale download", store_key)
                set_path = download_dish_set_sales(
                    page,
                    start_date=month.first_day_iso,
                    end_date=month.last_day_iso,
                    store_name=store.pos_name,
                    output_dir=out_dir,
                )
                set_results[store_key] = set_path
                logger.info("[%s] POS set-sale → %s", store_key, set_path)
            except Exception:
                logger.exception("[%s] POS set-sale download failed (W=0 fallback)",
                                 store_key)
                set_results[store_key] = None

        if owns_browser:
            try:
                context.storage_state(path=str(storage_path))
            except Exception:
                pass
            context.close()
            browser.close()
        else:
            try:
                page.close()
            except Exception:
                pass
    return results, set_results


def build_one(store_key: str, month: Month, out_root: Path,
              pos_path: Path | None,
              mb5b_shared: Path, zfi_shared: Path,
              template: Path,
              prev_report_root: Path | None = None,
              pos_set_path: Path | None = None,
              ) -> tuple[Path | None, str | None]:
    store = get_store(store_key)
    out_dir = out_root / store.werks
    fiori_target = _next_month(month)
    existing = out_dir / f"SGP-{store.sap_user}-盘点录入-{fiori_target.period}.xlsx"

    if existing.exists():
        fiori_path = existing
    else:
        try:
            fiori_path = download_fiori_stocktake(
                store, fiori_target, out_dir,
                headless=False, use_entry=True,
            )
        except Exception as exc:
            return None, f"Fiori: {exc}"

    if pos_path is None:
        return None, "POS unavailable"

    # Auto-discover the previous month's per-store report (drives
    # 上月盘点结果 + the report sheet's 单价差异 col). Falls back to
    # None if missing — pipeline then clears 上月盘点结果 as before.
    prev_report_path = None
    if prev_report_root is not None:
        prev_month = _prev_month(month)
        candidate = (prev_report_root / store.werks /
                     f"{store.werks}-盘点结果-{prev_month.period}.xlsx")
        if candidate.exists():
            prev_report_path = candidate
            logger.info("[%s] prev_report → %s", store_key, candidate)

    try:
        artifacts = build_inventory_report(
            sap_user=store_key,
            month_str=f"{month.year:04d}-{month.month:02d}",
            out_dir=out_dir,
            skip_pos=True,
            skip_fiori=True,
            skip_mb5b=True,
            skip_zfi0156=True,
            fiori_path=fiori_path,
            mb5b_path=mb5b_shared,
            zfi0156_path=zfi_shared,
            pos_path=pos_path,
            pos_set_path=pos_set_path,
            prev_report_path=prev_report_path,
            template_path=template,
            assemble=True,
        )
        return artifacts.report, None
    except Exception as exc:
        logger.exception("[%s] pipeline failed", store_key)
        return None, f"pipeline: {exc}"


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

    p = argparse.ArgumentParser(prog="inventory_check.all_stores")
    p.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-04")
    p.add_argument("--output-root", default="output/inventory-check",
                   help="Base dir; per-month outputs go to <root>/<period>-all/<werks>/")
    p.add_argument("--template", required=True,
                   help="Previous month's manual workbook (e.g. CA08-盘点结果-202603.xlsx)")
    p.add_argument("--mb5b-file", default=None,
                   help="Region-wide MB5B (default: <output-root>/<period>/mb5b<period>.xls)")
    p.add_argument("--zfi0156-file", default=None,
                   help="Region-wide ZFI0156 from prior month "
                        "(default: <output-root>/<period>/zfi0156-<prev_period>.xlsx)")
    p.add_argument("--skip", default=",".join(DEFAULT_SKIP),
                   help=f"Comma-separated store keys to skip (default: {','.join(DEFAULT_SKIP)})")
    p.add_argument("--stores", default=None,
                   help="Comma-separated subset to run (overrides ALL_STORES − --skip)")
    p.add_argument("--prev-report-root", default=None,
                   help="Root dir to auto-discover prev-month per-store reports "
                        "(populates 上月盘点结果 sheet). Looks for "
                        "<root>/<werks>/<werks>-盘点结果-<prev_period>.xlsx. "
                        "Default: <output-root>/<prev_period>-all/")
    args = p.parse_args(argv)

    month = parse_month(args.month)
    skip_set = {s.strip() for s in args.skip.split(",") if s.strip()}
    if args.stores:
        stores = [s.strip() for s in args.stores.split(",") if s.strip()]
    else:
        stores = [s for s in ALL_STORES if s not in skip_set]

    out_root = Path(args.output_root) / f"{month.period}-all"
    out_root.mkdir(parents=True, exist_ok=True)

    shared_dir = Path(args.output_root) / month.period
    mb5b = Path(args.mb5b_file) if args.mb5b_file else shared_dir / f"mb5b{month.period}.xls"
    zfi = (Path(args.zfi0156_file) if args.zfi0156_file
           else shared_dir / f"zfi0156-{_prev_month(month).period}.xlsx")
    template = Path(args.template).expanduser()

    for path, label in [(mb5b, "MB5B"), (zfi, "ZFI0156"), (template, "template")]:
        if not path.exists():
            logger.error("%s not found: %s", label, path)
            return 2

    logger.info("running %d stores: %s", len(stores), stores)
    logger.info("month=%s  out_root=%s", args.month, out_root)
    logger.info("MB5B=%s  ZFI=%s  template=%s", mb5b, zfi, template)

    # VPN: SAP Fiori (per-store stocktake) and IPMS need it. POS is public
    # but checking up-front is cheap and lets us fail fast.
    try:
        from vpn import ensure_vpn
        ensure_vpn()
    except Exception as exc:
        logger.error("VPN check failed: %s", exc)
        return 2

    prev_month = _prev_month(month)
    prev_report_root = (Path(args.prev_report_root).expanduser()
                        if args.prev_report_root
                        else Path(args.output_root) / f"{prev_month.period}-all")
    if prev_report_root.exists():
        logger.info("prev-report root: %s", prev_report_root)
    else:
        logger.info("no prev-report root at %s — 上月盘点结果 will be cleared",
                    prev_report_root)
        prev_report_root = None

    pos_paths, pos_set_paths = download_pos_for_all(stores, month, out_root)

    rows = []
    for s in stores:
        rep, err = build_one(s, month, out_root, pos_paths.get(s),
                             mb5b, zfi, template,
                             prev_report_root=prev_report_root,
                             pos_set_path=pos_set_paths.get(s))
        rows.append((s, rep, err))

    print()
    print("=" * 70)
    print("DETAILED REPORT SUMMARY")
    print("=" * 70)
    ok = 0
    for k, rep, err in rows:
        if rep:
            print(f"  ✓ {k:<7s} → {rep}")
            ok += 1
        else:
            print(f"  ✗ {k:<7s} — {err}")
    print(f"\n{ok}/{len(rows)} stores succeeded")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
