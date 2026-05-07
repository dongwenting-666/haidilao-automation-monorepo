"""Debug login — log URL changes, capture API traffic, wait for post-login API calls."""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://pos.superhi-tech.com"
HAR_PATH = Path("output/pos-traffic.har")
STORAGE_PATH = Path.home() / ".haidilao" / "pos-storage-state.json"


def main() -> None:
    HAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            record_har_path=str(HAR_PATH),
            record_har_url_filter="**/*",
        )
        page = context.new_page()

        # Log all API requests in real-time
        def on_request(request):
            url = request.url
            if not any(x in url for x in ['.js', '.css', '.png', '.jpg', '.svg', '.ico', '.woff', '.ttf']):
                print(f"  → {request.method} {url[:150]}")

        def on_response(response):
            url = response.url
            if not any(x in url for x in ['.js', '.css', '.png', '.jpg', '.svg', '.ico', '.woff', '.ttf']):
                print(f"  ← {response.status} {url[:150]}")

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)

        print(f"\nInitial URL: {page.url}")
        print("\n1. Scan QR to log in")
        print("2. After login, browse the POS pages you want to automate")
        print("3. Close the browser window when done\n")

        # Wait for browser to close
        try:
            while True:
                time.sleep(1)
                try:
                    _ = page.url  # will throw if browser is closed
                except Exception:
                    print("\nBrowser closed.")
                    break
        except KeyboardInterrupt:
            print("\nInterrupted.")

        try:
            context.storage_state(path=str(STORAGE_PATH))
            print(f"💾 Session saved to {STORAGE_PATH}")
        except Exception:
            pass
        context.close()
        print(f"📡 HAR saved to {HAR_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
