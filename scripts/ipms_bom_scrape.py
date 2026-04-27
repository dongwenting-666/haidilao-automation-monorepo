from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


TARGET_URL = "https://ipms-global.superhi-tech.com/myMessage"
OUTPUT_DIR = Path("/Users/mu/Downloads/ipms-bom-export")
STATE_PATH = OUTPUT_DIR / "storage-state.json"
JSON_PATH = OUTPUT_DIR / "canada-bom.json"
CSV_PATH = OUTPUT_DIR / "canada-bom.csv"

STORE_NAMES = [
    "加拿大一店",
    "加拿大二店",
    "加拿大三店",
    "加拿大四店",
    "加拿大五店",
    "加拿大六店",
    "加拿大七店",
    "加拿大八店",
]


def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _dump_html(page, name: str) -> None:
    (OUTPUT_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8")


def _dump_text(page, name: str) -> None:
    (OUTPUT_DIR / f"{name}.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")


def _dump_png(page, name: str) -> None:
    page.screenshot(path=str(OUTPUT_DIR / f"{name}.png"), full_page=True)


def _click_first(page, selectors: list[str], *, timeout: int = 3000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(timeout=timeout)
            locator.click()
            return True
        except Exception:
            continue
    return False


def _goto_menu(page) -> None:
    menu_steps = [
        ["text=产品审批流", "role=link[name='产品审批流']", "role=button[name='产品审批流']"],
        ["text=BOM管理", "role=link[name='BOM管理']", "role=button[name='BOM管理']"],
        ["text=产品BOM", "role=link[name='产品BOM']", "role=button[name='产品BOM']"],
    ]
    for step in menu_steps:
        if not _click_first(page, step, timeout=5000):
            raise RuntimeError(f"Could not click menu step: {step[0]}")
        page.wait_for_timeout(1200)


def _choose_region(page) -> None:
    trigger_selectors = [
        "label:has-text('海外') + *",
        "label:has-text('区域') + *",
        "label:has-text('区域') >> xpath=following::*[contains(@class,'select')][1]",
        "input[placeholder*='区域']",
    ]
    if not _click_first(page, trigger_selectors, timeout=2500):
        return
    page.wait_for_timeout(500)
    _click_first(page, ["text=加拿大", "role=option[name='加拿大']"], timeout=3000)
    page.wait_for_timeout(800)


def _open_store_filter(page) -> bool:
    return _click_first(
        page,
        [
            "label:has-text('门店') + *",
            "label:has-text('门店选择') + *",
            "label:has-text('门店') >> xpath=following::*[contains(@class,'select')][1]",
            "input[placeholder*='门店']",
        ],
        timeout=2500,
    )


def _choose_store(page, store_name: str) -> None:
    if not _open_store_filter(page):
        raise RuntimeError("Could not open store filter")
    page.wait_for_timeout(500)
    search_boxes = page.locator("input")
    for idx in range(search_boxes.count()):
        try:
            box = search_boxes.nth(idx)
            if box.is_visible():
                box.fill(store_name)
                break
        except Exception:
            continue
    page.wait_for_timeout(500)
    if not _click_first(page, [f"text={store_name}", f"role=option[name='{store_name}']"], timeout=3000):
        raise RuntimeError(f"Could not choose store {store_name}")
    page.wait_for_timeout(800)


def _click_query(page) -> None:
    _click_first(page, ["text=查询", "role=button[name='查询']", "button:has-text('查询')"], timeout=3000)
    page.wait_for_timeout(1500)


def _extract_table_rows(page, store_name: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    table_rows = page.locator("table tbody tr")
    count = min(table_rows.count(), 300)
    for i in range(count):
        row = table_rows.nth(i)
        try:
            texts = [_slug(t) for t in row.locator("td").all_inner_texts()]
        except Exception:
            continue
        if not texts:
            continue
        rows.append(
            {
                "store": store_name,
                "row_index": str(i + 1),
                "columns": json.dumps(texts, ensure_ascii=False),
            }
        )
    return rows


def _save(rows: list[dict[str, str]]) -> None:
    JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["store", "row_index", "columns"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    _ensure_output_dir()
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(OUTPUT_DIR / "playwright-profile"),
            headless=False,
            slow_mo=200,
        )
        page = context.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        # Manual login window if needed.
        deadline = time.time() + 300
        tick = 0
        while time.time() < deadline:
            try:
                current_url = page.url
                current_title = page.title()
                if tick % 5 == 0:
                    print(f"[wait] url={current_url} title={current_title}", flush=True)
                if page.locator("text=产品审批流").count() or page.locator("text=BOM管理").count() or page.locator("text=产品BOM").count():
                    break
                if "login" not in current_url.lower() and "myMessage" not in current_url:
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)
            tick += 1

        page.wait_for_timeout(2000)
        _dump_html(page, "landing")
        _dump_text(page, "landing")
        _dump_png(page, "landing")
        print(f"[landing] url={page.url} title={page.title()}", flush=True)
        _goto_menu(page)
        _choose_region(page)

        all_rows: list[dict[str, str]] = []
        for store_name in STORE_NAMES:
            _choose_store(page, store_name)
            _click_query(page)
            _dump_html(page, f"{store_name}-list")
            all_rows.extend(_extract_table_rows(page, store_name))

        _save(all_rows)
        context.storage_state(path=str(STATE_PATH))
        print(f"Saved {len(all_rows)} rows to {CSV_PATH}")
        page.wait_for_timeout(1000)
        context.close()


if __name__ == "__main__":
    main()
