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

_REPORT_MENU_IDS: dict[str, str] = {
    REPORT_DAILY: "89809ff6-a4fe-4fd7-853d-49315e51b2ec",
    REPORT_TIME_PERIOD: "4ee6d680-5b6c-4b35-ac8f-b9851be038da",
    REPORT_24H: "2090b625-1a31-4dcb-adc8-f4e5b7d33339",
}

# Timing constants (seconds) — tuned for the Quick BI SPA rendering speed
_NAVIGATION_SETTLE = 3
_SPA_RENDER_WAIT = 2
_POST_QUERY_WAIT = 5
_DATE_INPUT_DELAY = 0.3
_DATE_CONFIRM_DELAY = 0.5
_EXPORT_DIALOG_DELAY = 1
_IFRAME_TIMEOUT_MS = 60_000
_IFRAME_LOAD_TIMEOUT_MS = 15_000
_IFRAME_POLL_INTERVAL = 1
_SELECTOR_WAIT_TIMEOUT_MS = 30_000
_EXPORT_BTN_TIMEOUT_MS = 10_000
_DOWNLOAD_TIMEOUT_MS = 120_000

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _get_dashboard_iframe(page: Page, timeout_ms: int = _IFRAME_TIMEOUT_MS) -> Frame:
    """Return the dashboard content iframe, waiting for it to be ready."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for frame in page.frames:
            if "dashboard/view/pc.htm" in frame.url:
                try:
                    frame.wait_for_load_state("domcontentloaded", timeout=_IFRAME_LOAD_TIMEOUT_MS)
                    frame.query_selector_all("input")
                    return frame
                except PlaywrightError:
                    logger.debug("Iframe not ready yet, retrying…")
                    time.sleep(_IFRAME_POLL_INTERVAL)
                    continue
        time.sleep(_IFRAME_POLL_INTERVAL)
    raise QBITimeoutError("Dashboard iframe did not appear")


def navigate_to_report(page: Page, report_name: str) -> Frame:
    """Navigate to a report by loading the correct dashboard URL directly.

    This is more reliable than sidebar clicks because it forces a full
    page reload, avoiding stale iframe references.

    Args:
        page: The main Quick BI page (not the iframe).
        report_name: One of REPORT_DAILY, REPORT_TIME_PERIOD, REPORT_24H.

    Returns:
        The dashboard iframe Frame after navigation is complete.
    """
    menu_id = _REPORT_MENU_IDS.get(report_name)
    if not menu_id:
        raise QBIError(f"Unknown report: {report_name}")

    url = (
        f"{BASE_URL}/product/view.htm"
        f"?module=dashboard&productId={_PRODUCT_ID}&menuId={menu_id}"
    )
    logger.info("Navigating to report: %s", report_name)
    page.goto(url, wait_until="networkidle")
    time.sleep(_NAVIGATION_SETTLE)

    iframe = _get_dashboard_iframe(page)
    # Wait for date inputs or query button to appear (SPA rendering)
    try:
        iframe.wait_for_selector(
            'input[placeholder="请选择时间"], button.query-button',
            timeout=_SELECTOR_WAIT_TIMEOUT_MS,
        )
    except PlaywrightError:
        logger.warning(
            "Date inputs / query button not found after 30s for %s — "
            "report may not have loaded correctly",
            report_name,
        )
    time.sleep(_SPA_RENDER_WAIT)
    logger.info("Report loaded: %s", report_name)
    return iframe


def set_date_range(iframe: Frame, start: str, end: str) -> None:
    """Set the date range filter and click 查询.

    Args:
        iframe: The dashboard content iframe.
        start: Start date as YYYY-MM-DD (e.g. "2026-02-01").
        end: End date as YYYY-MM-DD (e.g. "2026-02-28").
    """
    if not _DATE_PATTERN.match(start) or not _DATE_PATTERN.match(end):
        raise QBIError(f"Dates must be YYYY-MM-DD, got start={start!r} end={end!r}")

    date_inputs = iframe.query_selector_all('input[placeholder="请选择时间"]')
    if len(date_inputs) < 2:
        raise QBIError(
            f"Expected 2 date inputs, found {len(date_inputs)} — page may not have loaded"
        )

    logger.info("Setting date range: %s → %s", start, end)
    kb = iframe.page.keyboard

    for inp, value in [(date_inputs[0], start), (date_inputs[1], end)]:
        inp.click()
        time.sleep(_DATE_INPUT_DELAY)
        # Select all existing text and replace via keyboard
        inp.evaluate("el => el.select && el.select()")
        kb.press("Control+a")
        kb.type(value, delay=50)
        kb.press("Enter")
        time.sleep(_DATE_CONFIRM_DELAY)
        # Dismiss any open date picker popup by pressing Escape
        kb.press("Escape")
        time.sleep(_DATE_INPUT_DELAY)

    # Click 查询 button
    query_btn = iframe.query_selector("button.query-button, button:has-text('查 询')")
    if not query_btn:
        raise QBIError("查询 button not found")
    query_btn.click()
    logger.info("Query submitted, waiting for data…")
    time.sleep(_POST_QUERY_WAIT)
    iframe.wait_for_load_state("networkidle")


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

    # Click the floating 导出 button
    export_btn = iframe.wait_for_selector(
        'li.preview-mini-menu-list-item:has-text("导出")',
        timeout=_EXPORT_BTN_TIMEOUT_MS,
    )
    if not export_btn:
        raise QBIError("导出 button not found")
    export_btn.click()
    logger.info("Export dialog opened")
    time.sleep(_EXPORT_DIALOG_DELAY)

    # Ensure EXCEL is selected (it's the default, but be explicit)
    excel_radio = iframe.query_selector('input.ant-radio-input[value="EXCEL"]')
    if excel_radio and not excel_radio.is_checked():
        excel_radio.click()

    # Ensure 全部内容 is selected
    full_content = iframe.query_selector(
        '.ant-radio-wrapper:has-text("全部内容")'
    )
    if full_content:
        checked = full_content.query_selector(".ant-radio-checked")
        if not checked:
            full_content.click()

    # Click 确定 and wait for download
    page = iframe.page
    with page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as download_info:
        confirm_btn = iframe.query_selector(
            '.ant-modal .ant-btn-primary:has-text("确 定")'
        )
        if not confirm_btn:
            raise QBIError("确定 button not found in export dialog")
        confirm_btn.click()
        logger.info("Export confirmed, waiting for download…")

    download = download_info.value
    dest = download_dir / download.suggested_filename
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
) -> Path:
    """Navigate to a report, set date range, and export as EXCEL.

    This is the main high-level function combining navigation + date + export.

    Args:
        page: The main Quick BI page (after login).
        report_name: One of REPORT_DAILY, REPORT_TIME_PERIOD, REPORT_24H.
        start_date: Start date as YYYY-MM-DD.
        end_date: End date as YYYY-MM-DD.
        download_dir: Directory to save the exported file.

    Returns:
        Path to the downloaded XLSX file.
    """
    if start_date > end_date:
        raise QBIError(f"start_date ({start_date}) must be <= end_date ({end_date})")
    iframe = navigate_to_report(page, report_name)
    set_date_range(iframe, start_date, end_date)
    return export_excel(iframe, download_dir)
