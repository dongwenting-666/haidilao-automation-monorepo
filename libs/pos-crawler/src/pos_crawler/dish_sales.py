"""菜品销售报表 (sales-by-dish) export from POS Hongfutai.

Why this exists
---------------
The POS UI's "导出" button calls ``/repDishSale/export`` which returns an OSS
download URL that points to a 1-row stub xlsx — broken on the server side.
Instead, we replay the same paginated **list** API the table uses
(``/repDishSale/listDishPotSale``) and assemble our own xlsx.

Auth model
----------
POS uses session cookies (``_nb_ioWEgULi: expires=-1``) that die on browser
close, so a Playwright ``storage_state`` reload alone is not enough — every
run needs a fresh, *live* browser session. Pass in a ``Page`` that's already
logged in (typically from ``POSSession.interactive_login_and_keep_open()``),
or use the CLI which wraps the login + download in one process.

Output schema (sheet ``红火台销售汇总``)
--------------------------------------
14 columns. The first 12 match the analyst's manual layout:

    检索 | 门店名称 | 编码 | 菜品编码 | 菜品短编码 | 菜品名称 |
    规格 | 出品数量 | 退菜数量 | 实际出品数据 | 大类名称 | 子类名称

The trailing two (菜品单价, 菜品单位) are appended for downstream use
(inventory-check 计算 sheet K/L). They're not part of the manual layout
and don't break any of the manual's formulas, which all reference cols
A–J only.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from playwright.sync_api import Page, Error as PlaywrightError

from pos_crawler.errors import POSError, POSTimeoutError

logger = logging.getLogger(__name__)

REPORT_URL = "https://pos.superhi-tech.com/#/shopMgr/saleDishPotReport"

# 显示方式 radio: 1 = 分列 (per-day rows), 2 = 汇总 (one row per dish for the date range)
GROUP_COLLECT_BY_COLUMN = 1
GROUP_COLLECT_SUMMARY = 2

# Output xlsx column order — first 12 match the manual 红火台销售汇总 sheet,
# trailing two are appended (see module docstring).
OUTPUT_COLUMNS: tuple[str, ...] = (
    "检索",
    "门店名称",
    "编码",
    "菜品编码",
    "菜品短编码",
    "菜品名称",
    "规格",
    "出品数量",
    "退菜数量",
    "实际出品数据（出品数量-退菜数量）",
    "大类名称",
    "子类名称",
    "菜品单价",
    "菜品单位",
)


def api_row_to_output_row(row: dict[str, Any]) -> list[Any]:
    """Map one /repDishSale/listDishPotSale row to the manual-report layout.

    Pure (no I/O) so this can be unit-tested without a browser.

    检索 is the analyst's lookup key — concatenated as
    ``{shopName}{dishCode}{dishUnicode}{standardName}``. The 编码 column is
    intentionally blank in the manual report; we keep it empty to match.
    """
    shop = (row.get("shopName") or "").strip()
    code = row.get("dishCode") or ""
    unicode_code = row.get("dishUnicode") or ""
    spec = (row.get("standardName") or "").strip()
    produced = row.get("producedNumber") or 0
    retreated = row.get("retreatNumber") or 0
    return [
        f"{shop}{code}{unicode_code}{spec}",  # 检索
        shop,                                  # 门店名称
        "",                                    # 编码 — blank in manual report
        code,                                  # 菜品编码
        unicode_code,                          # 菜品短编码
        (row.get("dishName") or "").strip(),   # 菜品名称
        spec,                                  # 规格
        produced,                              # 出品数量
        retreated,                             # 退菜数量
        produced - retreated,                  # 实际出品数据
        (row.get("bigDishTypeName") or ""),    # 大类名称
        (row.get("smallDishTypeName") or ""),  # 子类名称
        row.get("dishPrice"),                  # 菜品单价
        (row.get("unit") or ""),               # 菜品单位
    ]


def _switch_store(page: Page, store_name: str, *, timeout_ms: int = 10_000) -> None:
    """Switch the top-right store via the header dropdown.

    The dropdown uses Element UI: trigger ``.header-dropdown .el-dropdown-link``,
    options ``.header-dropdown-menu .el-dropdown-menu__item``. Hover (not click)
    is what Element UI listens for to expand by default — but a real click works
    too. We click and verify the text changed.
    """
    trigger = page.locator(".header-dropdown .el-dropdown-link").first
    trigger.wait_for(state="visible", timeout=timeout_ms)
    current = (trigger.inner_text() or "").strip()
    if current.startswith(store_name):
        logger.info("Store already on %s", store_name)
        return
    logger.info("Switching store: %s → %s", current, store_name)
    # Element UI uses mouseenter to open; click works too. Try both.
    trigger.hover()
    time.sleep(0.3)
    trigger.click()
    time.sleep(0.3)
    option = page.locator(
        f'.header-dropdown-menu .el-dropdown-menu__item:has-text("{store_name}")'
    ).first
    option.wait_for(state="visible", timeout=timeout_ms)
    option.click()
    # Wait for the trigger text to update.
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        new_text = (trigger.inner_text() or "").strip()
        if store_name in new_text:
            logger.info("Store now on %s", new_text)
            return
        time.sleep(0.3)
    raise POSError(
        f"Store switch to {store_name!r} did not take effect "
        f"(trigger still shows {current!r})"
    )


_PICKER_HEADER_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")


def _parse_picker_header(text: str) -> tuple[int, int]:
    """Parse Element UI's range-picker header (e.g. ``"2026 年 3 月"``)."""
    m = _PICKER_HEADER_RE.search(text or "")
    if not m:
        raise POSError(f"Cannot parse picker header: {text!r}")
    return int(m.group(1)), int(m.group(2))


def _month_delta(from_ym: tuple[int, int], to_ym: tuple[int, int]) -> int:
    """Months from ``from_ym`` to ``to_ym``. Negative = step backwards."""
    return (to_ym[0] - from_ym[0]) * 12 + (to_ym[1] - from_ym[1])


def _pick_end_side(start_ym: tuple[int, int], end_ym: tuple[int, int]) -> str:
    """Which calendar (left or right) holds the end day.

    ``"is-left"`` if same month as start; ``"is-right"`` if start_month + 1.
    Wider ranges raise — the inventory-check use case is monthly, and walking
    the right calendar across multiple months would need separate navigation.
    """
    diff = _month_delta(start_ym, end_ym)
    if diff == 0:
        return "is-left"
    if diff == 1:
        return "is-right"
    raise POSError(
        f"End {end_ym} is {diff} months after start {start_ym}; "
        "calendar driver only supports same-month or adjacent-month ranges"
    )


def _set_date_range(page: Page, start: str, end: str) -> None:
    """Set the date range via the calendar picker UI.

    Element UI's date editor doesn't reliably commit text-input changes —
    even with the native-setter + dispatched-input-event trick the picker's
    internal v-model stays stale, so the subsequent 查询 fires with the
    pre-existing date and the API returns rows for the wrong window. Drive
    the picker the way a user would: open it, navigate the left calendar's
    month via the prev/next arrows until it shows ``start``, click the start
    day, then click the end day on whichever side (left = same month, right
    = next month) it lives on.
    """
    start_y, start_m, start_d = (int(p) for p in start.split("-"))
    end_y, end_m, end_d = (int(p) for p in end.split("-"))
    start_ym, end_ym = (start_y, start_m), (end_y, end_m)

    editor = page.locator(".el-date-editor--daterange").first
    editor.wait_for(state="visible", timeout=10_000)
    inp = editor.locator("input.el-input__inner").first
    inp.click()

    panel = page.locator(".el-picker-panel.el-date-range-picker").first
    panel.wait_for(state="visible", timeout=5_000)
    time.sleep(0.4)

    def _read_left_header() -> tuple[int, int]:
        text = panel.locator(
            ".is-left .el-date-range-picker__header > div"
        ).first.inner_text()
        return _parse_picker_header(text)

    cur_ym = _read_left_header()
    delta = _month_delta(cur_ym, start_ym)
    if delta < 0:
        prev_btn = panel.locator(".is-left .el-icon-arrow-left").first
        for _ in range(-delta):
            prev_btn.click()
            time.sleep(0.15)
    elif delta > 0:
        next_btn = panel.locator(".is-left .el-icon-arrow-right").first
        for _ in range(delta):
            next_btn.click()
            time.sleep(0.15)

    cur_ym = _read_left_header()
    if cur_ym != start_ym:
        raise POSError(
            f"Calendar navigation failed: target {start_ym}, "
            f"left header shows {cur_ym}"
        )

    def _click_day_on(side: str, day: int) -> None:
        # td.available excludes prev-month / next-month gray cells, which is
        # important — those would click into an adjacent month and Element UI
        # would interpret it as cross-month range selection.
        cells = panel.locator(f".{side} td.available")
        count = cells.count()
        target = str(day)
        for i in range(count):
            cell = cells.nth(i)
            if cell.inner_text().strip() == target:
                cell.click()
                return
        raise POSError(f"Day {day} not found among available cells in {side}")

    _click_day_on("is-left", start_d)
    time.sleep(0.2)
    _click_day_on(_pick_end_side(start_ym, end_ym), end_d)

    # Picker self-closes after the second day click. Don't fail hard if it
    # lingers — the v-model update has already happened.
    try:
        panel.wait_for(state="hidden", timeout=3_000)
    except PlaywrightError:
        page.keyboard.press("Escape")
    time.sleep(0.3)

    actual = inp.input_value()
    expected = f"{start},{end}"
    if actual != expected:
        logger.warning(
            "Picker committed but input shows %r (expected %r) — proceeding",
            actual, expected,
        )
    else:
        logger.info("Date range set via calendar: %s", actual)


def _set_group_collect(page: Page, group_collect: int) -> None:
    """Select 显示方式 radio (1 = 分列, 2 = 汇总).

    Match by label text — more robust than ``[value="2"]`` because Element
    UI sometimes binds the value via v-model to a number while the DOM
    attribute differs (and was empty in some renders).
    """
    label_text = "分列" if group_collect == GROUP_COLLECT_BY_COLUMN else "汇总"
    # The clickable element is the .el-radio label wrapping the .el-radio__label span.
    radio_label = page.locator(
        f'label.el-radio:has(.el-radio__label:has-text("{label_text}"))'
    ).first
    if radio_label.count() == 0:
        raise POSError(
            f"显示方式 radio with label {label_text!r} not found"
        )
    radio_label.click(timeout=5_000)
    time.sleep(0.2)


def _click_query(page: Page) -> None:
    """Click the form-area 查 询 button.

    Element UI renders all dialog buttons into the DOM up-front (hidden
    until the dialog opens), so a CSS-selector match by ``el-button--primary``
    + text alone can grab a hidden dialog button — clicking it does nothing
    visible but consumes the click. The previous ``:not(.el-dialog *)`` CSS
    filter was unreliable across builds. Iterating over role-based matches
    and picking the first **visible** one is sturdier.
    """
    btns = page.get_by_role("button", name=re.compile(r"查\s*询"))
    count = btns.count()
    if count == 0:
        raise POSError("查 询 button not found")
    for i in range(count):
        btn = btns.nth(i)
        if btn.is_visible() and not btn.is_disabled():
            btn.scroll_into_view_if_needed(timeout=3_000)
            # Dispatch the full mouse sequence rather than a single click —
            # Element UI buttons sometimes have separate mousedown/mouseup
            # handlers (focus + activate) that a synthesized .click() skips
            # in some build configs. force=True also bypasses Playwright's
            # actionability check (we already verified visible+enabled).
            try:
                btn.dispatch_event("mousedown")
                btn.dispatch_event("mouseup")
                btn.click(timeout=5_000, force=True)
            except PlaywrightError as e:
                logger.warning("Primary click path failed: %s — retrying", e)
                btn.click(timeout=5_000)
            logger.info("Clicked 查 询 (match %d/%d)", i + 1, count)
            return
    raise POSError(
        f"No visible 查 询 button among {count} matches — "
        "form may not have mounted yet"
    )


def _click_next_page(page: Page) -> bool:
    """Advance to the next page in the el-pagination strip.

    Returns True if a click happened; False if there's no next page.
    """
    next_btn = page.locator(".el-pagination .btn-next").first
    if next_btn.count() == 0:
        return False
    # Element UI disables the button by setting `disabled` on the <button>.
    if next_btn.is_disabled():
        return False
    next_btn.click()
    return True


# Reverse-engineered from POS frontend bundle (headMgr.build.<hash>.js).
# Every API request is signed with MD5 over a sorted key=value string plus
# this hardcoded secret. The exact algorithm is in the bundle's ``sign`` util.
_SIG_SECRET = "w83keis394jc55klua36"


def _sign_params(url_path: str, params: dict[str, str]) -> str:
    """MD5 sig matching POS's frontend ``sign()`` util.

    Format: ``MD5(<path>?<k1=v1&k2=v2&...sorted> + SECRET)`` — keys sorted
    lexicographically, values RAW (not URL-encoded). The path is the bare
    request path stripped of scheme+host.
    """
    import hashlib
    if params:
        sorted_kv = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        msg = f"{url_path}?{sorted_kv}"
    else:
        msg = url_path
    return hashlib.md5((msg + _SIG_SECRET).encode("utf-8")).hexdigest()


def _extract_creds(storage_blob: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Walk through every value in localStorage + sessionStorage looking for
    a JSON object that has shopId / userName / userId fields, and pull the
    Token out of sessionStorage. Returns ``{shopId, userName, userId, Token}``
    or None if any of those are missing.

    POS stores user info under keys that vary across builds (``user``,
    ``employeeInfo``, ``loginInfo``, ``loginContext``, ``app-state``, …)
    so a substring search through every value is more robust than guessing.
    """
    import json
    wanted = {"shopId", "userName", "userId"}
    creds: dict[str, str] = {}
    for bucket in ("localStorage", "sessionStorage"):
        for value in (storage_blob.get(bucket) or {}).values():
            if creds:
                break
            if not value or not isinstance(value, str):
                continue
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                continue
            for candidate in _iter_candidate_objects(parsed):
                if isinstance(candidate, dict) and wanted.issubset(candidate.keys()):
                    creds = {k: str(candidate[k]) for k in wanted}
                    break
    if not creds:
        return None
    # Token is stored as a plain string under a top-level "Token" key in
    # sessionStorage — the bundle reads ``sessionStorage.Token``.
    token = (storage_blob.get("sessionStorage") or {}).get("Token")
    if not token:
        return None
    creds["Token"] = token
    return creds


def _iter_candidate_objects(obj: Any, depth: int = 0):
    """Yield obj, then each of its values up to 2 levels deep. Skip lists
    of primitives and avoid runaway recursion."""
    if depth > 2:
        return
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_candidate_objects(v, depth + 1)


def _navigate_and_fetch_via_api(
    page: Page,
    *,
    start_date: str,
    end_date: str,
    group_collect: int,
    page_size: int = 500,
    max_pages: int = 200,
    per_page_timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Navigate to the report and replay the list API with our own params.

    The report page in this POS build does NOT auto-fire ``listDishPotSale``
    on mount, and the form's 查询 button has unreliable Vue v-model commits
    when we set the date programmatically — so we sidestep both. The SPA
    persists the user's session creds (``shopId``/``userName``/``userId``)
    in localStorage, and ``window.app.$axios`` carries the request-signing
    interceptor. We pull the creds, then call the API directly via axios,
    one page at a time, until the API tells us we've consumed every page.
    """
    import urllib.parse

    def on_response(resp: Any) -> None:
        url = resp.url
        # Track every same-origin XHR for diagnostics — if we don't catch
        # listDishPotSale, the dump tells us what the SPA *did* hit.
        if "pos.superhi-tech.com" in url and "?" in url:
            all_seen.append(url)
        if "listDishPotSale" not in url or captured_url:
            return
        captured_url["url"] = url

    # The list API URL is the same across every store/user — only the
    # per-session creds (shopId/userName/userId) change. The SPA stores
    # those in localStorage/Vuex and reads them on every API call, so we
    # can pull them without waiting for any XHR to fire.
    LIST_API = "https://pos.superhi-tech.com:8032/repDishSale/listDishPotSale"

    page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_selector(
            ".el-date-editor--daterange", state="visible", timeout=20_000
        )
    except PlaywrightError:
        raise POSError(
            "Date editor never rendered after navigating to REPORT_URL — "
            "the SPA likely fell back to its default landing."
        )

    # Probe localStorage and window.app for the creds. shopId/userName/
    # userId are often stored under different keys across POS builds, so
    # pull everything that looks like a candidate and let the caller pick.
    creds_blob = page.evaluate("""
        () => {
            const out = {localStorage: {}, sessionStorage: {}};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out.localStorage[k] = localStorage.getItem(k);
            }
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                out.sessionStorage[k] = sessionStorage.getItem(k);
            }
            return out;
        }
    """)
    creds = _extract_creds(creds_blob)
    if not creds:
        # Dump key names to help diagnose where the creds live in this build.
        keys_dump = (
            "localStorage keys: " + ", ".join(sorted(creds_blob.get("localStorage", {}).keys())) +
            "\nsessionStorage keys: " + ", ".join(sorted(creds_blob.get("sessionStorage", {}).keys()))
        )
        raise POSError(
            f"Could not find shopId/userName/userId in localStorage or "
            f"sessionStorage. {keys_dump}"
        )

    logger.info(
        "Credentials extracted: shopId=%s userName=%s (token len=%d)",
        creds["shopId"], creds["userName"], len(creds["Token"]),
    )

    parsed = urllib.parse.urlparse(LIST_API)
    list_path = parsed.path  # ``/repDishSale/listDishPotSale``

    rows: list[dict[str, Any]] = []
    page_num = 1
    while page_num <= max_pages:
        # Build params and sign them in Python — same MD5 algorithm as the
        # POS bundle's ``sign()`` util. Values are RAW for signing
        # (frontend doesn't url-encode before signing) but the URL we send
        # must be url-encoded.
        signed_params = {
            "groupCollect": str(group_collect),
            "date": f"{start_date},{end_date}",
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "shopId": creds["shopId"],
            "userName": creds["userName"],
            "userId": creds["userId"],
        }
        signed_params["sig"] = _sign_params(list_path, signed_params)
        full_url = LIST_API + "?" + urllib.parse.urlencode(signed_params)
        # Fetch from the page's origin so the session cookies attach
        # automatically. Token + timestamp go in headers per the bundle.
        result = page.evaluate(
            """
            async ({url, token}) => {
                try {
                    const r = await fetch(url, {
                        credentials: 'include',
                        headers: {
                            'Token': token,
                            'timestamp': String(Date.now()),
                        },
                    });
                    let body;
                    try { body = await r.json(); }
                    catch (e) { body = {result: r.status, message: 'non-json body'}; }
                    return {status: r.status, body};
                } catch (e) {
                    return {status: -1, body: {result: -1, message: 'fetch threw: ' + (e && e.message)}};
                }
            }
            """,
            {"url": full_url, "token": creds["Token"]},
        )
        body = result.get("body") if isinstance(result, dict) else None
        if not body or body.get("result") != 200:
            raise POSError(
                f"API returned non-200 on page {page_num}: "
                f"http_status={result.get('status')!r} body={str(body)[:400]!r}"
            )
        data = body.get("data") or {}
        page_rows = data.get("list") or []
        rows.extend(page_rows)
        total = data.get("total", 0)
        total_pages = data.get("pages", 1)
        logger.info(
            "  page %d/%d: +%d rows (running total=%d / %d)",
            page_num, total_pages, len(page_rows), len(rows), total,
        )
        if page_num >= total_pages or not page_rows:
            break
        page_num += 1
    return rows


def _collect_pages(page: Page, *, max_pages: int = 100, per_page_timeout_s: float = 30.0) -> list[dict[str, Any]]:
    """Drive the report's pagination and accumulate every list row.

    Strategy: install a ``page.on("response")`` listener BEFORE clicking 查询,
    accumulate ``data.list`` from each ``listDishPotSale`` response, and stop
    when ``isLastPage`` flips True or when we've consumed the page-count we
    learned on the first response.
    """
    rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {"total_pages": None, "got_pages": 0, "last_seen": 0.0, "errors": []}

    def on_response(resp: Any) -> None:
        if "listDishPotSale" not in resp.url:
            return
        try:
            j = resp.json()
        except Exception as e:
            state["errors"].append(f"json decode: {e}")
            return
        if j.get("result") != 200:
            state["errors"].append(f"api result {j.get('result')}: {j.get('message')}")
            return
        data = j.get("data") or {}
        page_rows = data.get("list") or []
        rows.extend(page_rows)
        if state["total_pages"] is None:
            state["total_pages"] = data.get("pages") or 1
            logger.info(
                "First page received: %d rows, total=%d, pages=%d",
                len(page_rows), data.get("total", 0), state["total_pages"],
            )
        state["got_pages"] += 1
        state["last_seen"] = time.monotonic()
        logger.info(
            "  page %d/%s: +%d rows (running total=%d)",
            state["got_pages"], state["total_pages"], len(page_rows), len(rows),
        )

    page.on("response", on_response)
    try:
        _click_query(page)
        # Wait for the first response.
        deadline = time.monotonic() + per_page_timeout_s
        while time.monotonic() < deadline and state["total_pages"] is None:
            time.sleep(0.2)
        if state["total_pages"] is None:
            raise POSTimeoutError(
                f"No listDishPotSale response within {per_page_timeout_s}s of clicking 查询"
            )

        total_pages = state["total_pages"]
        if total_pages > max_pages:
            raise POSError(
                f"Refusing to paginate {total_pages} pages (max_pages={max_pages}); "
                "raise max_pages or narrow the date range."
            )

        # Click next-page until we've got every page.
        while state["got_pages"] < total_pages:
            advanced = _click_next_page(page)
            if not advanced:
                logger.warning(
                    "Pagination next button became unavailable at page %d/%d",
                    state["got_pages"], total_pages,
                )
                break
            # Wait for one more response to arrive.
            target_count = state["got_pages"] + 1
            deadline = time.monotonic() + per_page_timeout_s
            while time.monotonic() < deadline and state["got_pages"] < target_count:
                time.sleep(0.2)
            if state["got_pages"] < target_count:
                raise POSTimeoutError(
                    f"Page {target_count} did not arrive within {per_page_timeout_s}s"
                )
    finally:
        page.remove_listener("response", on_response)

    if state["errors"]:
        # Non-fatal: report the first one as a warning but trust the rows we got.
        logger.warning("Non-fatal API errors during pagination: %s", state["errors"][:3])
    return rows


def _write_xlsx(rows: list[dict[str, Any]], output_path: Path) -> Path:
    """Write rows to xlsx with sheet 红火台销售汇总 + the 12-column schema."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "红火台销售汇总"
    ws.append(list(OUTPUT_COLUMNS))
    for row in rows:
        ws.append(api_row_to_output_row(row))
    wb.save(output_path)
    logger.info("Wrote %d rows to %s", len(rows), output_path)
    return output_path


def download_dish_sales(
    page: Page,
    *,
    start_date: str,
    end_date: str,
    store_name: str,
    output_dir: Path,
    group_collect: int = GROUP_COLLECT_SUMMARY,
    output_filename: str | None = None,
) -> Path:
    """Drive the POS sales-by-dish report and write a single xlsx.

    Args:
        page: A logged-in Playwright Page (POS session must be live; storage-
            state reuse alone won't work because POS uses session cookies).
        start_date / end_date: ``YYYY-MM-DD`` strings, inclusive.
        store_name: Display name shown in the top-right dropdown
            (e.g. ``"加拿大八店"``). Must be present in the user's
            permission list, otherwise the switcher's option list won't
            contain it and the call raises POSError.
        output_dir: Directory to write the xlsx into; created if missing.
        group_collect: ``GROUP_COLLECT_SUMMARY`` (汇总, default — one row per
            dish/spec for the entire date range, what 红火台销售汇总 expects)
            or ``GROUP_COLLECT_BY_COLUMN`` (分列, per-day rows).
        output_filename: Override the default filename. If omitted, uses
            ``{store_name}-菜品销售汇总-{YYYYMMDD}-{YYYYMMDD}.xlsx``.

    Returns:
        Path to the written xlsx.
    """
    if not _is_iso_date(start_date) or not _is_iso_date(end_date):
        raise POSError(
            f"Dates must be YYYY-MM-DD; got start={start_date!r} end={end_date!r}"
        )
    if start_date > end_date:
        raise POSError(f"start_date > end_date: {start_date} > {end_date}")

    logger.info(
        "Downloading 菜品销售报表 — store=%s dates=%s→%s group_collect=%d",
        store_name, start_date, end_date, group_collect,
    )

    # Store switch must happen BEFORE we land on the report page — POS routes
    # the user back to /#/index/main when the store changes, blowing away any
    # filter state. Wait for the header on whatever page we're on, switch
    # there, then go to the report.
    page.wait_for_selector(".header-dropdown", state="visible", timeout=30_000)
    time.sleep(1)
    _switch_store(page, store_name)
    time.sleep(1)

    # API-replay path: the form-driven path is unreliable in this POS
    # build — driving the date editor by calendar clicks updates the input
    # value but Vue's filter v-model doesn't always commit, so the click
    # on 查询 fires nothing. We sidestep all that by extracting the
    # shopId/userName/userId from any XHR the page issues on mount and
    # calling ``listDishPotSale`` directly through ``window.app.$axios``.
    rows = _navigate_and_fetch_via_api(
        page, start_date=start_date, end_date=end_date, group_collect=group_collect
    )

    if output_filename is None:
        output_filename = _default_filename(store_name, start_date, end_date)
    return _write_xlsx(rows, Path(output_dir) / output_filename)


def _default_filename(store_name: str, start_date: str, end_date: str) -> str:
    """Default xlsx filename: ``{store}-菜品销售汇总-{YYYYMMDD}-{YYYYMMDD}.xlsx``.

    Compact (no dashes) date format matches the analyst's manual export
    convention so files sort lexically by date in the inventory-check folder.
    """
    return (
        f"{store_name}-菜品销售汇总-"
        f"{start_date.replace('-', '')}-{end_date.replace('-', '')}.xlsx"
    )


def _is_iso_date(s: str) -> bool:
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True
