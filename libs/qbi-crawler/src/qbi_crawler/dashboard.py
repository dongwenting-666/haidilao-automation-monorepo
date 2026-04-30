"""Haidilao overseas data portal — dashboard navigation and export."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, Frame, Page

from qbi_crawler.constants import BASE_URL
from qbi_crawler.errors import QBIError, QBITimeoutError

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_SUBDIR = "qbi"

# Dashboard identifiers for the Haidilao overseas data portal (internal)
_PRODUCT_ID = "1fcba94f-c81d-4595-80cc-dac5462e0d24"

# Sidebar report names → menuIds (discovered from the portal SPA)
REPORT_DAILY = "门店经营日报数据"
REPORT_TIME_PERIOD = "分时段营业数据"
REPORT_24H = "24小时营业数据"
# 菜品专题 → 菜品销售 → 海外套餐销售明细 — has additional 国家 filter
REPORT_OVERSEAS_SET_MEAL = "海外套餐销售明细"

_REPORT_MENU_IDS: dict[str, str] = {
    REPORT_DAILY: "89809ff6-a4fe-4fd7-853d-49315e51b2ec",
    REPORT_TIME_PERIOD: "4ee6d680-5b6c-4b35-ac8f-b9851be038da",
    REPORT_24H: "2090b625-1a31-4dcb-adc8-f4e5b7d33339",
    # Discovered live 2026-04-29 (login → 菜品专题 → 菜品销售 → leaf click,
    # then verified via tools/verify_qbi_ids.py — body header reads
    # "海外套餐销售明细"). NOTE: the menuId here is the 菜品专题 *tab*
    # menuId, not a leaf-specific one — that's how QBI routes this leaf.
    REPORT_OVERSEAS_SET_MEAL: "3a4a0da7-f754-4b79-a662-5b49def5b716",
}

# pageIds for direct dashboard view navigation (bypasses SPA iframe loading)
_REPORT_PAGE_IDS: dict[str, str] = {
    REPORT_DAILY: "1c4b2f41-a491-4568-bedc-67d7fd4cf93d",
    REPORT_TIME_PERIOD: "3bd957ee-c5f4-431a-a8a3-26d83f705f59",
    REPORT_OVERSEAS_SET_MEAL: "55c5d6ee-297c-44ad-842c-51e2a279c690",
}

# Timing constants (seconds) — tuned for the Quick BI SPA rendering speed
_NAVIGATION_SETTLE = 10
_SPA_RENDER_WAIT = 2
_POST_QUERY_WAIT = 5
_DATE_INPUT_DELAY = 0.3
_DATE_CONFIRM_DELAY = 0.5
_EXPORT_DIALOG_DELAY = 1
_IFRAME_TIMEOUT_MS = 120_000
_IFRAME_LOAD_TIMEOUT_MS = 15_000
_IFRAME_POLL_INTERVAL = 1
_SELECTOR_WAIT_TIMEOUT_MS = 60_000
_EXPORT_BTN_TIMEOUT_MS = 10_000
_DOWNLOAD_TIMEOUT_MS = 120_000

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _get_dashboard_iframe(page: Page, timeout_ms: int = _IFRAME_TIMEOUT_MS) -> Frame:
    """Return the dashboard content iframe, waiting for it to be ready.

    The Quick BI SPA creates the iframe element early but the content frame
    URL stays empty for ~30-45 seconds until the JS fully loads.  We poll
    ``page.frames`` until a frame with ``dashboard/view/pc.htm`` in its URL
    appears, then wait for ``domcontentloaded``.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    start = time.monotonic()
    logger.info("Waiting for dashboard iframe (timeout=%ds)…", timeout_ms // 1000)
    while time.monotonic() < deadline:
        elapsed = time.monotonic() - start
        # Check page.frames for a frame with the correct URL and rendered content
        for frame in page.frames:
            if frame.url and "dashboard/view/pc.htm" in frame.url:
                try:
                    # Verify the frame has actual rendered content (inputs or tables)
                    inputs = frame.query_selector_all("input")
                    if inputs:
                        logger.info("Dashboard iframe ready after %.1fs", elapsed)
                        return frame
                except PlaywrightError:
                    pass  # Frame may be detached
        if int(elapsed) % 15 == 0 and int(elapsed) > 0:
            logger.info("%.0fs: still waiting for iframe…", elapsed)
        time.sleep(_IFRAME_POLL_INTERVAL)
    raise QBITimeoutError("Dashboard iframe did not appear")


def _wait_for_spa_body(page: Page, timeout_s: int = 120) -> None:
    """Wait for the Quick BI SPA to finish rendering (body has text content)."""
    for i in range(timeout_s):
        try:
            body = page.inner_text("body")
            if body.strip():
                logger.info("SPA body rendered after %ds", i + 1)
                return
        except PlaywrightError:
            pass  # Page may still be loading
        time.sleep(1)
    raise QBITimeoutError("SPA body did not render")


def _click_sidebar_item(page: Page, report_name: str) -> None:
    """Click the sidebar menu item matching the report name."""
    items = page.get_by_text(report_name, exact=True)
    if items.count() == 0:
        raise QBIError(f"Sidebar item '{report_name}' not found")
    items.first.click()
    logger.debug("Clicked sidebar item: %s", report_name)


def navigate_to_report(page: Page, report_name: str) -> Frame:
    """Navigate to a report and return its iframe Frame.

    Strategy: load the product page directly (which embeds the dashboard in
    an iframe), wait for the SPA to render, click the sidebar to trigger
    iframe content loading, then wait for the iframe to have date inputs.

    Args:
        page: The main Quick BI page (after login).
        report_name: One of REPORT_DAILY, REPORT_TIME_PERIOD, REPORT_24H.

    Returns:
        The dashboard iframe Frame with rendered content.
    """
    menu_id = _REPORT_MENU_IDS.get(report_name)
    page_id = _REPORT_PAGE_IDS.get(report_name)
    if not menu_id:
        raise QBIError(f"Unknown report: {report_name}")

    # Navigate directly to the dashboard content URL inside the product frame
    # This is faster than loading the full product page SPA
    if page_id:
        url = (
            f"{BASE_URL}/dashboard/view/pc.htm"
            f"?pageId={page_id}&menuId={menu_id}"
            f"&dd_orientation=auto&productView=&__pcDevice__=true"
        )
    else:
        url = (
            f"{BASE_URL}/product/view.htm"
            f"?module=dashboard&productId={_PRODUCT_ID}&menuId={menu_id}"
        )

    logger.info("Navigating to report: %s", report_name)
    page.goto(url, wait_until="domcontentloaded", timeout=180_000)

    # Wait for the SPA to render date inputs (takes ~60-120s on slow networks)
    logger.info("Waiting for report content to render…")
    try:
        page.wait_for_selector("input", timeout=180_000, state="attached")
    except PlaywrightError:
        raise QBITimeoutError(
            f"Report {report_name} inputs did not render within 180s"
        )
    # Give extra time for all components to finish rendering
    time.sleep(5)
    logger.info("Report loaded: %s", report_name)
    return page.main_frame


def _navigate_and_click_date(page: Page, target_date: str) -> None:
    """Click a date cell in the open Ant Design calendar picker.

    The Ant Design RangePicker renders ``<td title="YYYY-MM-DD">`` cells.
    If the target month is not visible, click the prev/next month arrows
    to navigate to it first.  Uses ``force=True`` because Ant Design
    RangePicker has two panels and navigation buttons on one panel may be
    overlapped or hidden by the other.
    """
    from datetime import date as Date

    target = Date.fromisoformat(target_date)

    def _find_visible_btn(selector: str):
        """Return the first visible button matching selector, or first if none visible."""
        btns = page.query_selector_all(selector)
        for b in btns:
            try:
                if b.is_visible():
                    return b
            except PlaywrightError:
                pass
        return btns[0] if btns else None

    for attempt in range(36):  # max 36 month navigations (3 years)
        cell = page.query_selector(f'td[title="{target_date}"]')
        if cell:
            cell.click()
            logger.debug("Clicked date cell: %s", target_date)
            return

        # Determine current visible month from an in-view cell
        first_visible = page.query_selector('td.ant-picker-cell-in-view[title]')
        if first_visible:
            vis_date = Date.fromisoformat(first_visible.get_attribute('title'))
            months_diff = (target.year - vis_date.year) * 12 + (target.month - vis_date.month)
        else:
            months_diff = -1  # Assume backward

        logger.debug("Calendar nav: target=%s, visible=%s, months_diff=%d, attempt=%d",
                      target_date, first_visible.get_attribute('title') if first_visible else '?',
                      months_diff, attempt)

        if months_diff == 0:
            # Same month but cell not found yet — wait and retry
            time.sleep(0.5)
            continue

        # Pick navigation button
        btn = None
        if months_diff < 0:
            # Need to go backward
            if abs(months_diff) > 6:
                btn = _find_visible_btn('button.ant-picker-header-super-prev-btn')
            if not btn:
                btn = _find_visible_btn('button.ant-picker-header-prev-btn')
        else:
            # Need to go forward
            if months_diff > 6:
                btn = _find_visible_btn('button.ant-picker-header-super-next-btn')
            if not btn:
                btn = _find_visible_btn('button.ant-picker-header-next-btn')

        if btn:
            btn.click(force=True)
            time.sleep(0.5)
        else:
            logger.warning("No navigation button found for months_diff=%d", months_diff)
            break

    raise QBIError(f"Could not find date cell for {target_date} in calendar")


def set_country(iframe: Frame, country: str) -> None:
    """Pick a country in the 国家 dropdown.

    Used by reports like 海外套餐销售明细 that have a country filter alongside
    the date range. The Quick BI country dropdown is an Ant Design Select with
    placeholder ``请选择`` (or ``请选择（多选）`` for multi-select). We locate
    it by finding a Select whose preceding label text contains "国家", click it
    open, then click the option whose text equals *country*.

    Args:
        iframe: The dashboard content iframe.
        country: Display name of the country (e.g. "加拿大", "美国").
    """
    page = iframe.page

    # The 国家 selector is identified by the form-item label "国家". Quick BI
    # renders form-item labels as <span> or <label> next to the .ant-select.
    # We find the select by walking from the label.
    logger.info("Setting country filter: %s", country)
    label_to_select_js = """
        () => {
            // Walk every label/span and look for one whose text starts with "国家"
            const labels = Array.from(document.querySelectorAll('label, span, div'));
            for (const el of labels) {
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt === '国家' || txt === '国家:' || txt.startsWith('国家')) {
                    // Find the next Ant Select sibling within the same form-item ancestor
                    let p = el.parentElement;
                    for (let depth = 0; depth < 5 && p; depth++, p = p.parentElement) {
                        const sel = p.querySelector('.ant-select');
                        if (sel) {
                            sel.setAttribute('data-qbi-country', '1');
                            return true;
                        }
                    }
                }
            }
            return false;
        }
    """
    found = page.evaluate(label_to_select_js)
    if not found:
        # The selector is in the iframe, not the outer page
        found = iframe.evaluate(label_to_select_js)
    if not found:
        raise QBIError("国家 dropdown not found")

    # Click to open
    select_locator = iframe.locator('.ant-select[data-qbi-country="1"]')
    if select_locator.count() == 0:
        select_locator = page.locator('.ant-select[data-qbi-country="1"]')
    select_locator.first.click()
    time.sleep(0.5)

    # Options render in a portal at body root — look on page, not iframe
    option = page.locator(
        f'.ant-select-item-option:has-text("{country}")'
    ).first
    if option.count() == 0:
        # Fallback: option lives inside the iframe's portal
        option = iframe.locator(
            f'.ant-select-item-option:has-text("{country}")'
        ).first
    if option.count() == 0:
        raise QBIError(f"Country option {country!r} not in dropdown")
    option.click()
    time.sleep(0.5)
    # Close dropdown so it doesn't overlap the 查询 button
    page.keyboard.press("Escape")
    time.sleep(_DATE_INPUT_DELAY)


def set_date_range(
    iframe: Frame,
    start: str,
    end: str,
    *,
    country: str | None = None,
) -> None:
    """Set the date range filter (and optionally a country) then click 查询.

    Args:
        iframe: The dashboard content iframe.
        start: Start date as YYYY-MM-DD (e.g. "2026-02-01").
        end: End date as YYYY-MM-DD (e.g. "2026-02-28").
        country: Optional country name (e.g. "加拿大") for reports that have
            a 国家 dropdown alongside the date range (e.g. 海外套餐销售明细).
    """
    if not _DATE_PATTERN.match(start) or not _DATE_PATTERN.match(end):
        raise QBIError(f"Dates must be YYYY-MM-DD, got start={start!r} end={end!r}")

    # Wait for date inputs to appear (SPA may still be rendering)
    page = iframe.page
    date_inputs = []
    for _ in range(30):
        date_inputs = page.query_selector_all('input[placeholder="请选择时间"]')
        if len(date_inputs) >= 2:
            break
        time.sleep(1)
    if len(date_inputs) < 2:
        raise QBIError(
            f"Expected 2 date inputs, found {len(date_inputs)} — page may not have loaded"
        )

    logger.info("Setting date range: %s → %s", start, end)

    # Click the start date input to open the Ant Design RangePicker calendar
    date_inputs[0].click()
    time.sleep(1)

    # Navigate the calendar to the correct month for the start date and click it.
    # Ant Design calendar cells have title="YYYY-MM-DD" attributes.
    _navigate_and_click_date(page, start)
    time.sleep(_DATE_CONFIRM_DELAY)

    # Click the end date in the calendar (picker stays open after start date click)
    _navigate_and_click_date(page, end)
    time.sleep(_DATE_CONFIRM_DELAY)

    # Dismiss any remaining picker popup
    page.keyboard.press("Escape")
    time.sleep(_DATE_INPUT_DELAY)

    # Optional country filter (must run before 查询)
    if country:
        set_country(iframe, country)

    # Click 查询 button
    query_btn = iframe.query_selector("button.query-button, button:has-text('查 询')")
    if not query_btn:
        raise QBIError("查询 button not found")
    query_btn.click()
    logger.info("Query submitted, waiting for data…")
    time.sleep(_POST_QUERY_WAIT)
    iframe.wait_for_load_state("domcontentloaded")


def _click_export_and_wait_for_dialog(
    iframe: Frame, page: Page, *, max_attempts: int = 3
) -> None:
    """Click the 导出 button and wait for the export modal to appear.

    QBI's export dialog occasionally fails to render on the first click.
    This helper retries the click up to *max_attempts* times, dismissing any
    stale modal between attempts.
    """
    _DIALOG_SELECTOR = '.ant-modal-wrap.mix-export-modal-wrapper'
    _EXPORT_BTN = 'li.preview-mini-menu-list-item:has-text("导出")'

    for attempt in range(1, max_attempts + 1):
        # Dismiss any leftover modal from a previous attempt
        stale = page.query_selector(_DIALOG_SELECTOR)
        if stale and stale.is_visible():
            close_btn = page.query_selector('.ant-modal-wrap.mix-export-modal-wrapper .ant-modal-close')
            if close_btn:
                close_btn.click()
                time.sleep(0.5)

        export_btn = iframe.query_selector(_EXPORT_BTN)
        if not export_btn:
            export_btn = iframe.wait_for_selector(_EXPORT_BTN, timeout=_EXPORT_BTN_TIMEOUT_MS)
        if not export_btn:
            raise QBIError("导出 button not found")

        export_btn.click()
        logger.info("Export menu item clicked (attempt %d/%d), waiting for dialog…", attempt, max_attempts)

        try:
            page.wait_for_selector(
                _DIALOG_SELECTOR,
                timeout=15_000,
                state="visible",
            )
            logger.info("Export dialog appeared")
            return  # success
        except PlaywrightError:
            logger.warning(
                "Export dialog did not appear (attempt %d/%d)",
                attempt, max_attempts,
            )
            if attempt < max_attempts:
                # Press Escape to clear any half-rendered state, then retry
                page.keyboard.press("Escape")
                time.sleep(2)

    raise QBIError(
        f"Export dialog failed to render after {max_attempts} attempts"
    )


def export_excel(iframe: Frame, download_dir: Path) -> Path:
    """Click the export button, confirm EXCEL export, and return the downloaded file.

    Args:
        iframe: The dashboard content iframe.
        download_dir: Directory where the file will be saved.

    Returns:
        Path to the downloaded file (filename is server-assigned, typically .xlsx).
    """
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    page = iframe.page

    # Click 导出 and wait for the export modal (with retries)
    _click_export_and_wait_for_dialog(iframe, page)
    time.sleep(1)

    # Search for dialog elements on the page (modal is outside any iframe)
    search_ctx = page

    # Ensure EXCEL is selected (it's the default, but be explicit)
    excel_radio = search_ctx.query_selector('input.ant-radio-input[value="EXCEL"]')
    if excel_radio and not excel_radio.is_checked():
        excel_radio.click()

    # Ensure 全部内容 is selected
    full_content = search_ctx.query_selector(
        '.ant-radio-wrapper:has-text("全部内容")'
    )
    if full_content:
        checked = full_content.query_selector(".ant-radio-checked")
        if not checked:
            full_content.click()

    # Click 确定 and wait for download
    time.sleep(1)

    with page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as download_info:
        # Try multiple selectors for the confirm button
        confirm_btn = None
        for selector in [
            '.ant-modal .ant-btn-primary:has-text("确 定")',
            '.ant-modal .ant-btn-primary:has-text("确定")',
            'button.ant-btn-primary:has-text("确 定")',
            'button.ant-btn-primary:has-text("确定")',
        ]:
            confirm_btn = search_ctx.query_selector(selector)
            if confirm_btn and confirm_btn.is_visible():
                break
            confirm_btn = None
        if not confirm_btn:
            raise QBIError("确定 button not found in export dialog")
        confirm_btn.click()
        logger.info("Export confirmed, waiting for download…")

    download = download_info.value
    dest = download_dir / download.suggested_filename
    # Avoid overwriting if QBI returns the same filename for multiple downloads
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 2
        while dest.exists():
            dest = download_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    download.save_as(dest)
    logger.info("Downloaded: %s", dest)
    return dest


def download_report(
    page: Page,
    report_name: str,
    *,
    start_date: str,
    end_date: str,
    download_dir: Path,
    country: str | None = None,
) -> Path:
    """Navigate to a report, set date range, and export as EXCEL.

    This is the main high-level function combining navigation + date + export.

    Args:
        page: The main Quick BI page (after login).
        report_name: One of REPORT_DAILY, REPORT_TIME_PERIOD, REPORT_24H,
            REPORT_OVERSEAS_SET_MEAL.
        start_date: Start date as YYYY-MM-DD.
        end_date: End date as YYYY-MM-DD.
        download_dir: Directory to save the exported file.
        country: Optional country filter (e.g. "加拿大"). Required for
            reports with a 国家 dropdown (REPORT_OVERSEAS_SET_MEAL); ignored
            otherwise. Will raise if the dropdown isn't on the page.

    Returns:
        Path to the downloaded XLSX file.
    """
    if start_date > end_date:
        raise QBIError(f"start_date ({start_date}) must be <= end_date ({end_date})")
    iframe = navigate_to_report(page, report_name)
    set_date_range(iframe, start_date, end_date, country=country)
    return export_excel(iframe, download_dir)
