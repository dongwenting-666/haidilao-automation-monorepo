"""Capture POS API traffic. Opens browser, waits for manual close, saves HAR."""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://pos.superhi-tech.com"
HAR_PATH = Path("output/pos-traffic.har")
STORAGE_PATH = Path.home() / ".haidilao" / "pos-storage-state.json"


def main() -> None:
    HAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    pw_cm = sync_playwright()
    pw = pw_cm.start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(
        record_har_path=str(HAR_PATH),
        record_har_url_filter="**/*",
    )
    page = context.new_page()

    # Track API calls
    api_log: list[str] = []

    def on_response(response):
        url = response.url
        if any(x in url for x in ['.js', '.css', '.png', '.jpg', '.svg', '.ico', '.woff', '.ttf', '.gif', 'chunk-', '/assets/', '.map']):
            return
        line = f"{response.status:>4} {response.request.method:>4} {url[:150]}"
        api_log.append(line)
        print(line, flush=True)

    page.on("response", on_response)

    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    print(f"\nURL: {page.url}", flush=True)
    print("Scan QR → browse → close browser when done.\n", flush=True)

    # Handle Ctrl+C gracefully
    def cleanup(*_):
        print("\nSaving...", flush=True)
        try:
            context.storage_state(path=str(STORAGE_PATH))
            print(f"💾 {STORAGE_PATH}", flush=True)
        except Exception as e:
            print(f"Storage save failed: {e}", flush=True)
        try:
            context.close()
            print(f"📡 {HAR_PATH}", flush=True)
        except Exception:
            pass
        try:
            browser.close()
            pw_cm.__exit__(None, None, None)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Poll for browser close — handle page navigation gracefully
    while True:
        time.sleep(2)
        try:
            # Try to check if any page exists in the context
            pages = context.pages
            if not pages:
                print("\nAll pages closed.", flush=True)
                break
            # Try to evaluate on the first available page
            try:
                pages[0].evaluate("1")
            except Exception:
                # Page might be navigating — wait and retry once
                time.sleep(3)
                try:
                    pages = context.pages
                    if pages:
                        pages[0].evaluate("1")
                    else:
                        print("\nAll pages closed.", flush=True)
                        break
                except Exception:
                    # Check if browser process is still alive
                    try:
                        context.pages  # will throw if browser is gone
                        # Browser alive but page is navigating, keep waiting
                        continue
                    except Exception:
                        print("\nBrowser closed.", flush=True)
                        break
        except Exception:
            print("\nBrowser closed.", flush=True)
            break

    # Save everything
    try:
        context.storage_state(path=str(STORAGE_PATH))
        print(f"💾 {STORAGE_PATH}", flush=True)
    except Exception as e:
        print(f"Storage save failed: {e}", flush=True)
    try:
        context.close()
        print(f"📡 {HAR_PATH}", flush=True)
    except Exception as e:
        print(f"HAR save failed: {e}", flush=True)
    browser.close()
    pw_cm.__exit__(None, None, None)


if __name__ == "__main__":
    main()
