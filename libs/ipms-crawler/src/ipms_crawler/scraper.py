"""IPMS BOM export + download flow.

For each requested tab (菜品 / 锅底):
  1. Navigate to ``/approval/bomMgt/overseasBomList`` and click the tab.
  2. Set 区域 = 加拿大 (or whatever was passed).
  3. Click 查询 to filter, then 导出 to enqueue an export job.
  4. Open the download-log modal (the ⬇ icon in the header).
  5. Poll the modal until the newest row's status is ``已完成``.
  6. Click 下载 in that row, capture the download, save to ``output_dir``.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from ipms_crawler.auth import IPMSSession
from ipms_crawler.constants import BOM_URL, DEFAULT_OUTPUT_DIR
from ipms_crawler.errors import IPMSExportError, IPMSTimeoutError

logger = logging.getLogger(__name__)

# Tab labels as shown in the BOM page header.
TAB_DISHES = "菜品"
TAB_HOTPOT_BASE = "锅底"

DEFAULT_TABS: tuple[str, ...] = (TAB_DISHES, TAB_HOTPOT_BASE)
DEFAULT_REGION = "加拿大"

# How long to wait for an export job to flip to 已完成.
EXPORT_POLL_INTERVAL_S = 5
EXPORT_POLL_TIMEOUT_S = 240  # 4 min — exports normally finish in 30-60s


def _unique_path(target: Path) -> Path:
    """Return ``target`` if it doesn't exist; otherwise append _1/_2/…

    Pure helper — kept out of the download flow so it can be unit-tested
    without touching the browser.
    """
    if not target.exists():
        return target
    counter = 1
    while True:
        candidate = target.with_name(
            f"{target.stem}_{counter}{target.suffix}"
        )
        if not candidate.exists():
            return candidate
        counter += 1


def download_bom(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    tabs: tuple[str, ...] = DEFAULT_TABS,
    region: str = DEFAULT_REGION,
    headless: bool = True,
    skip_vpn: bool = False,
) -> list[Path]:
    """Run the full export flow for each tab; return saved file paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    with IPMSSession(headless=headless, skip_vpn=skip_vpn) as session:
        page = session.page
        try:
            page.goto(BOM_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightError as exc:
            if "ERR_ABORTED" not in str(exc):
                raise
            # The SPA's router hijacks navigation; the abort is harmless,
            # the page still renders. Wait for the tab strip instead.
            logger.info("goto aborted (SPA-intercepted), continuing")
        page.wait_for_selector(".el-tabs__item", state="visible", timeout=20_000)
        time.sleep(2)

        for tab in tabs:
            logger.info("=== Exporting tab: %s (region=%s) ===", tab, region)
            try:
                file_path = _export_one_tab(
                    page=page, tab=tab, region=region, output_dir=output_dir
                )
            except Exception:
                # On any failure, snapshot the DOM so we can debug.
                snap = output_dir / f"failure_{tab}_{int(time.time())}.png"
                try:
                    page.screenshot(path=str(snap), full_page=True)
                    logger.error("Diagnostic screenshot saved: %s", snap)
                except PlaywrightError:
                    pass
                raise
            saved.append(file_path)
            logger.info("✅ %s → %s", tab, file_path)

    return saved


def _export_one_tab(
    *, page: Page, tab: str, region: str, output_dir: Path
) -> Path:
    """Run the export+download flow for a single tab. Returns the saved file."""
    # 1. Click the tab. Tabs are at the top of the BOM page.
    _click_tab(page, tab)

    # 2. Pick region.
    _select_region(page, region)

    # 3. Click 查询 (search/filter).
    _click_button(page, "查询")
    # Wait for results table to refresh; the SPA may not have a clear signal,
    # so just give it a beat.
    time.sleep(2)

    # 4. Record the timestamp BEFORE clicking export, so we can match the
    #    new row in the download-log modal even if a previous export of the
    #    same tab is still listed.
    submit_marker = datetime.now(tz=ZoneInfo("America/Vancouver")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    logger.info("Submit marker (Vancouver): %s", submit_marker)

    # 5. Click 导出 to enqueue the export job.
    _click_button(page, "导出")
    # Confirmation modal appears: "下载请求已提交…". Close it.
    _close_modal(page)

    # 6. Open the download-log modal and wait for the newest row to complete.
    download_path = _wait_and_download_latest(
        page=page, output_dir=output_dir, submit_marker=submit_marker
    )
    return download_path


# ── UI helpers ─────────────────────────────────────────────────────────────


def _click_tab(page: Page, tab: str) -> None:
    """Click a top tab on the BOM page (菜品 / 锅底 / 非标规格菜品).

    Element UI tabs are ``.el-tabs__item``.
    """
    logger.debug("Clicking tab: %s", tab)
    try:
        page.wait_for_selector(".el-tabs__item", state="visible", timeout=15_000)
    except (PlaywrightError, PlaywrightTimeout):
        pass
    page.locator(".el-tabs__item", has_text=tab).first.click(timeout=10_000)
    time.sleep(2)


def _select_region(page: Page, region: str) -> None:
    """Open the 区域 dropdown (Element UI ``el-select``) and pick the region."""
    logger.debug("Selecting region: %s", region)
    # Tag the region el-select via JS — the form-item layout is:
    #   <div class="el-form-item"><label>区域</label>... <div class="el-select">...
    tagged = page.evaluate(
        """
        () => {
            const items = Array.from(document.querySelectorAll('.el-form-item'));
            for (const it of items) {
                const lbl = it.querySelector('.el-form-item__label, label');
                if (!lbl) continue;
                if ((lbl.textContent || '').trim() !== '区域') continue;
                const sel = it.querySelector('.el-select');
                if (!sel) continue;
                sel.setAttribute('data-ipms-pw', 'region-select');
                return true;
            }
            // Fallback — find any .el-select with placeholder hinting region.
            for (const sel of document.querySelectorAll('.el-select')) {
                const inp = sel.querySelector('input');
                if (inp && /区域/.test(inp.placeholder || '')) {
                    sel.setAttribute('data-ipms-pw', 'region-select');
                    return true;
                }
            }
            return false;
        }
        """
    )
    if not tagged:
        raise PlaywrightError("Could not locate 区域 el-select on the BOM page")

    page.locator(
        "[data-ipms-pw='region-select'] .el-select__wrapper, "
        "[data-ipms-pw='region-select'] .el-input, "
        "[data-ipms-pw='region-select']"
    ).first.click(timeout=10_000)

    # Wait for the open dropdown panel (there may be other closed
    # dropdowns with hidden options still in the DOM — pick the visible
    # panel, scroll the target into view inside it, then click via JS to
    # bypass Playwright's strict-visibility actionability check.
    page.wait_for_function(
        """region => {
            const panels = Array.from(document.querySelectorAll(
                '.el-select-dropdown, .el-popper'
            ));
            for (const p of panels) {
                const r = p.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (Array.from(p.querySelectorAll('.el-select-dropdown__item'))
                        .some(el => (el.textContent || '').trim() === region)) {
                    return true;
                }
            }
            return false;
        }""",
        arg=region,
        timeout=8_000,
    )
    clicked = page.evaluate(
        """region => {
            // Find the open panel that contains the target option.
            const panels = Array.from(document.querySelectorAll(
                '.el-select-dropdown, .el-popper'
            )).filter(p => {
                const r = p.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            });
            for (const p of panels) {
                const item = Array.from(p.querySelectorAll(
                    '.el-select-dropdown__item'
                )).find(el => (el.textContent || '').trim() === region);
                if (!item) continue;
                item.scrollIntoView({block: 'center', behavior: 'instant'});
                const r = item.getBoundingClientRect();
                const opts = {
                    bubbles: true, cancelable: true,
                    clientX: r.left + r.width / 2,
                    clientY: r.top + r.height / 2,
                    button: 0, buttons: 1,
                };
                item.dispatchEvent(new MouseEvent('mousedown', opts));
                item.dispatchEvent(new MouseEvent('mouseup', opts));
                item.dispatchEvent(new MouseEvent('click', opts));
                return true;
            }
            return false;
        }""",
        region,
    )
    if not clicked:
        raise PlaywrightError(
            f"Could not click region option {region!r} in open dropdown"
        )
    time.sleep(0.5)
    # Element UI sometimes leaves the dropdown open — Escape closes it.
    page.keyboard.press("Escape")
    time.sleep(0.3)


def _click_button(page: Page, label: str) -> None:
    """Click a button (Element-UI or native) by its visible label.

    Strategy: tag the first VISIBLE element matching ``button`` /
    ``[role=button]`` / ``.el-button`` whose trimmed text equals ``label``,
    then click it via Playwright. We match exact (trimmed) text so "导出"
    doesn't match "导出导入".
    """
    logger.debug("Clicking button: %s", label)
    tagged = page.evaluate(
        """
        (label) => {
            const sels = ['button', '[role=button]', '.el-button'];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const t = (el.textContent || '').trim();
                    if (t === label) {
                        el.setAttribute('data-ipms-pw', 'btn-target');
                        return true;
                    }
                }
            }
            return false;
        }
        """,
        label,
    )
    if not tagged:
        raise PlaywrightError(f"Could not find button {label!r}")
    page.locator("[data-ipms-pw='btn-target']").first.click(timeout=10_000)
    # Reset attribute for the next call.
    try:
        page.evaluate(
            """() => document.querySelectorAll('[data-ipms-pw=btn-target]')
                .forEach(e => e.removeAttribute('data-ipms-pw'))"""
        )
    except PlaywrightError:
        pass


def _close_modal(page: Page) -> None:
    """Close the topmost Element-UI dialog (.el-dialog or .el-message-box)."""
    logger.debug("Closing modal")
    for selector in [
        ".el-dialog__close",
        ".el-message-box__close",
        ".el-overlay-dialog .el-dialog__headerbtn",
    ]:
        try:
            page.locator(selector).last.click(timeout=2_000)
            time.sleep(0.5)
            return
        except (PlaywrightError, PlaywrightTimeout):
            continue
    # Fallback — try the 关闭 button if the dialog has one.
    try:
        page.locator(".el-button", has_text="关闭").last.click(timeout=2_000)
    except (PlaywrightError, PlaywrightTimeout):
        page.keyboard.press("Escape")
    time.sleep(0.5)


def _open_download_log(page: Page) -> None:
    """Click the 下载 icon in the top nav to open 下载日志管理.

    Identified by the icon class ``iconicon-xiazai`` (xiazai = 下载, pinyin)
    sitting in the top nav's ``.right-icon`` container.
    """
    logger.debug("Opening download log")
    tagged = page.evaluate(
        """
        () => {
            const icon = document.querySelector(
                '.right-icon [class*="iconicon-xiazai"], '
                + '[class*="iconicon-xiazai"]'
            );
            if (!icon) return false;
            // The clickable ancestor is the <a> wrapping the <i>.
            let el = icon;
            for (let i = 0; i < 3 && el && el.parentElement; i++) {
                if (el.tagName === 'A' || el.tagName === 'BUTTON') break;
                if (getComputedStyle(el).cursor === 'pointer') break;
                el = el.parentElement;
            }
            el.setAttribute('data-ipms-pw', 'download-log-trigger');
            return true;
        }
        """
    )
    if not tagged:
        raise IPMSExportError(
            "Could not find the download-log icon in the top nav"
        )

    page.locator("[data-ipms-pw='download-log-trigger']").first.click(
        timeout=10_000
    )
    # Wait for the modal — Element UI dialog with the right title.
    page.wait_for_selector(
        ".el-dialog:has-text('下载日志管理'), .el-drawer:has-text('下载日志管理')",
        state="visible",
        timeout=10_000,
    )
    time.sleep(0.5)
    # Reset the data attr so the same locator can be reused next call.
    try:
        page.evaluate(
            """() => document.querySelectorAll('[data-ipms-pw=download-log-trigger]')
                .forEach(e => e.removeAttribute('data-ipms-pw'))"""
        )
    except PlaywrightError:
        pass


def _wait_and_download_latest(
    *, page: Page, output_dir: Path, submit_marker: str
) -> Path:
    """Open the download log, poll for completion, click 下载, save the file."""
    _open_download_log(page)

    # Element UI table: each row is `.el-table__row`. The first row is the
    # newest export.
    deadline = time.monotonic() + EXPORT_POLL_TIMEOUT_S
    last_status = ""
    row_selector = (
        ".el-dialog .el-table__row, .el-drawer .el-table__row"
    )
    while time.monotonic() < deadline:
        try:
            first_row = page.locator(row_selector).first
            row_text = first_row.text_content(timeout=5_000) or ""
            if "已完成" in row_text:
                logger.info("Newest row complete — clicking 下载")
                # Tag the button via JS so we can attempt several click
                # strategies on a stable selector.
                tagged = page.evaluate(
                    """
                    () => {
                        const rows = document.querySelectorAll(
                            '.el-dialog .el-table__row, .el-drawer .el-table__row'
                        );
                        if (rows.length === 0) return false;
                        const btn = Array.from(rows[0].querySelectorAll('button'))
                            .find(b => (b.textContent || '').trim() === '下载');
                        if (!btn) return false;
                        btn.setAttribute('data-ipms-pw', 'dl-button');
                        return true;
                    }
                    """
                )
                if not tagged:
                    raise IPMSExportError(
                        "Could not tag the 下载 button in the first row"
                    )
                btn_loc = page.locator("[data-ipms-pw='dl-button']").first

                # Spy on every request fired during the click.
                seen_req: list[str] = []
                def _on_req(req):
                    seen_req.append(f"{req.method} {req.url[-150:]}")
                page.on("request", _on_req)

                try:
                    with page.expect_download(timeout=30_000) as dl_info:
                        # Try Playwright's native click first.
                        try:
                            btn_loc.click(timeout=3_000)
                        except (PlaywrightError, PlaywrightTimeout):
                            pass
                        time.sleep(2)
                        # If still no download, dispatch via JS event.
                        if not dl_info.is_done():
                            try:
                                btn_loc.dispatch_event("click")
                            except PlaywrightError:
                                pass
                            time.sleep(2)
                        # If still nothing, dispatch a full mouse sequence
                        # via JS (Element UI sometimes binds mousedown).
                        if not dl_info.is_done():
                            page.evaluate(
                                """() => {
                                    const btn = document.querySelector(
                                        "[data-ipms-pw='dl-button']"
                                    );
                                    if (!btn) return;
                                    const r = btn.getBoundingClientRect();
                                    const opts = {
                                        bubbles: true, cancelable: true,
                                        clientX: r.left + r.width / 2,
                                        clientY: r.top + r.height / 2,
                                        button: 0, buttons: 1,
                                    };
                                    btn.dispatchEvent(new MouseEvent('mousedown', opts));
                                    btn.dispatchEvent(new MouseEvent('mouseup', opts));
                                    btn.dispatchEvent(new MouseEvent('click', opts));
                                }"""
                            )
                    download = dl_info.value
                except PlaywrightTimeout:
                    logger.error(
                        "expect_download timed out. Requests fired since click:"
                    )
                    for r in seen_req[-30:]:
                        logger.error("  %s", r)
                    raise
                finally:
                    page.remove_listener("request", _on_req)
                    try:
                        page.evaluate(
                            "() => document.querySelectorAll('[data-ipms-pw=dl-button]')"
                            ".forEach(e => e.removeAttribute('data-ipms-pw'))"
                        )
                    except PlaywrightError:
                        pass

                suggested = download.suggested_filename or (
                    f"ipms_bom_{submit_marker}.xlsx"
                )
                safe_name = Path(suggested).name
                target = _unique_path(output_dir / safe_name)
                download.save_as(target)
                logger.info("Saved: %s", target)
                # Close the modal so the next tab starts clean.
                try:
                    page.locator(".el-dialog__close").last.click(timeout=2_000)
                except (PlaywrightError, PlaywrightTimeout):
                    page.keyboard.press("Escape")
                time.sleep(1)
                return target

            status_match = re.search(r"(导出中|已完成|失败|错误)", row_text)
            current = status_match.group(0) if status_match else "?"
            if current != last_status:
                logger.info("Export status: %s", current)
                last_status = current
            if "失败" in row_text or "错误" in row_text:
                raise IPMSExportError(
                    f"Export job failed (newest row): {row_text[:200]}"
                )
        except (PlaywrightError, PlaywrightTimeout) as exc:
            logger.debug("Poll iteration failed: %s", exc)

        time.sleep(EXPORT_POLL_INTERVAL_S)

    raise IPMSTimeoutError(
        f"Export job did not complete within {EXPORT_POLL_TIMEOUT_S}s"
    )
