"""Inspect the 国家 dropdown markup on the 海外套餐销售明细 report page.

Dumps every frame's body text + any element near "国家" so we can fix
the set_country() selector.

Usage:
    uv run --project libs/qbi-crawler python libs/qbi-crawler/tools/inspect_country_dropdown.py
"""
from __future__ import annotations

import logging
import os
import sys
import time

from dotenv import load_dotenv

from qbi_crawler import QBISession, REPORT_OVERSEAS_SET_MEAL, navigate_to_report


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger(__name__)

    username = os.environ.get("QBI_USERNAME", "")
    password = os.environ.get("QBI_PASSWORD", "")
    if not username or not password:
        print("ERROR: creds missing", file=sys.stderr)
        return 1

    with QBISession(username=username, password=password, headless=True) as session:
        page = session.page
        log.info("Navigating to %s...", REPORT_OVERSEAS_SET_MEAL)
        navigate_to_report(page, REPORT_OVERSEAS_SET_MEAL)
        time.sleep(3)

        log.info("Inspecting frames for 国家 markup...")
        for fr in page.frames:
            url = fr.url or ""
            try:
                count = fr.locator(':text("国家")').count()
            except Exception:
                count = 0
            log.info("  frame %s -> %d :text matches for 国家", url[:80], count)
            if count == 0:
                continue
            # Dump the HTML around the first 国家 match
            try:
                snippets = fr.evaluate("""
                    () => {
                        const out = [];
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            const txt = (el.textContent || '').trim();
                            // Match either exact "国家" or "国家" as a label-ish prefix
                            if (txt === '国家' || txt === '国家：' || txt === '国家:') {
                                // Walk up to find the form-item wrapper
                                let p = el;
                                let path = [];
                                for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
                                    path.push(p.tagName + '.' + (p.className || ''));
                                    if (p.parentElement) {
                                        const sibs = Array.from(p.parentElement.children);
                                        // Look for select widgets nearby
                                        for (const s of sibs) {
                                            const html = (s.outerHTML || '').slice(0, 500);
                                            if (/select|dropdown|combobox|input|wind/i.test(html)) {
                                                out.push({
                                                    label_text: txt,
                                                    label_path: path.slice(),
                                                    nearby_html: html,
                                                });
                                                if (out.length >= 3) return out;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        // Fallback: any element with title="国家" or aria-label="国家"
                        const titled = document.querySelectorAll('[title="国家"], [aria-label="国家"]');
                        for (const el of titled) {
                            out.push({
                                via: 'attribute',
                                tag: el.tagName,
                                class: el.className,
                                html: (el.outerHTML || '').slice(0, 600),
                            });
                        }
                        return out;
                    }
                """)
                print("=" * 80)
                print(f"FRAME: {url}")
                print(f"FOUND {len(snippets)} candidates:")
                for i, s in enumerate(snippets):
                    print(f"\n  [{i}] {s}")
                print()
            except Exception as e:
                print(f"  eval failed: {e}", file=sys.stderr)

        # Now open the dropdown and dump the popup markup
        log.info("Opening 国家 dropdown to inspect popup markup...")
        for fr in page.frames:
            if "dashboard/view/pc.htm" in (fr.url or ""):
                # Tag and click the .enum-select for 国家
                fr.evaluate("""
                    () => {
                        const labels = document.querySelectorAll('.query-field-label-name-text');
                        for (const lbl of labels) {
                            if ((lbl.textContent || '').trim() !== '国家') continue;
                            let p = lbl;
                            for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
                                if (p.classList && p.classList.contains('query-field')) {
                                    const sel = p.querySelector('.enum-select');
                                    if (sel) { sel.setAttribute('data-qbi-country', '1'); return; }
                                }
                            }
                        }
                    }
                """)
                fr.locator('.enum-select[data-qbi-country="1"]').first.click(timeout=5_000)
                time.sleep(4)
                # Dump everything that looks like a dropdown popup or option
                popup_dump = fr.evaluate("""
                    () => {
                        const out = {};
                        const popup = document.querySelector('.advance-select-popup');
                        if (popup) {
                            out.popup_full_html = popup.outerHTML;
                            // Tag structure of children
                            out.popup_children_outline = Array.from(popup.querySelectorAll('*')).slice(0, 80).map(el => ({
                                tag: el.tagName,
                                cls: (el.className || '').toString().slice(0, 120),
                                text: (el.textContent || '').trim().slice(0, 40),
                            }));
                        }
                        // Iterate document for any select-option-ish class
                        const optionClasses = [
                            'advance-select-option', 'select-option',
                            'advance-select-item', 'advance-select-list-item',
                            'select-list-item', 'enum-list-item',
                            'option-item', 'list-item',
                            'ant-select-item', 'ant-select-item-option',
                        ];
                        for (const cls of optionClasses) {
                            const els = document.querySelectorAll('.' + cls);
                            if (els.length > 0) {
                                out['count_' + cls] = els.length;
                                out['sample_' + cls] = Array.from(els).slice(0, 5).map(e => ({
                                    text: (e.textContent || '').trim().slice(0, 60),
                                    cls: (e.className || '').toString().slice(0, 200),
                                }));
                            }
                        }
                        return out;
                    }
                """)
                print("=" * 80)
                print("POPUP DUMP:")
                for k, v in popup_dump.items():
                    print(f"\n  [{k}]")
                    if isinstance(v, list):
                        for item in v:
                            print(f"    {item}")
                    elif isinstance(v, str):
                        print(f"    {v[:4000]}")
                    else:
                        print(f"    {v}")
                break

        page.screenshot(path="qbi_country.png", full_page=True)
        log.info("Screenshot saved to qbi_country.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
