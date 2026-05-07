"""POS authentication via Playwright with persistent browser storage state.

Login flow:
  1. First time / expired: launch headful browser, user scans Lark QR or
     enters SMS code manually, storage state is saved to disk.
  2. Subsequent runs: load saved storage state, verify session is alive,
     proceed headlessly.

Usage::

    # Interactive first login (opens a visible browser window)
    POSSession.interactive_login()

    # Automated headless session (uses saved state)
    with POSSession() as session:
        page = session.page
        # navigate, scrape, export, etc.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Self

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    sync_playwright,
)

from pos_crawler.constants import BASE_URL, DEFAULT_STORAGE_PATH
from pos_crawler.errors import POSLoginExpiredError, POSTimeoutError

logger = logging.getLogger(__name__)

_browser_installed = False
_browser_lock = threading.Lock()

# Pages that indicate an active session (not the login page)
_LOGIN_PATH_FRAGMENTS = ("/login", "/auth", "/sso")


def _is_login_page(url: str) -> bool:
    """Return True if the URL looks like a login/auth page."""
    from urllib.parse import urlparse

    path = urlparse(url).path.lower()
    return any(frag in path for frag in _LOGIN_PATH_FRAGMENTS)


class POSSession:
    """Manages a Playwright session to the Haidilao POS portal.

    Uses saved browser storage state for authentication.  If the state file
    doesn't exist or the session has expired, raises POSLoginExpiredError
    with instructions to run interactive_login().
    """

    def __init__(
        self,
        *,
        storage_path: Path = DEFAULT_STORAGE_PATH,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.headless = headless
        self.timeout_ms = timeout_ms

        self._pw_context: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise POSLoginExpiredError("Session not started — use as context manager")
        return self._page

    @staticmethod
    def _ensure_browser() -> None:
        """Install Chromium if not already present."""
        global _browser_installed
        if _browser_installed:
            return
        with _browser_lock:
            if _browser_installed:
                return
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    capture_output=True,
                )
                _browser_installed = True
            except FileNotFoundError:
                logger.debug("Playwright CLI not found — assuming browser present")
                _browser_installed = True
            except subprocess.CalledProcessError as exc:
                logger.warning("Browser install returned non-zero: %s", exc)
            except OSError:
                logger.warning("OS error during browser install", exc_info=True)

    def __enter__(self) -> Self:
        if not self.storage_path.exists():
            raise POSLoginExpiredError(
                f"No saved session at {self.storage_path}. "
                "Run `POSSession.interactive_login()` first to authenticate."
            )

        self._ensure_browser()
        self._pw_context = sync_playwright()
        pw = self._pw_context.start()
        self._browser = pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            storage_state=str(self.storage_path),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

        # Verify the session is still valid
        self._verify_session()
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            # Save refreshed cookies/tokens after each successful session
            if self._context and self.storage_path.parent.exists():
                try:
                    self._context.storage_state(path=str(self.storage_path))
                    logger.debug("Storage state refreshed at %s", self.storage_path)
                except PlaywrightError:
                    pass
        finally:
            try:
                if self._context:
                    self._context.close()
            finally:
                try:
                    if self._browser:
                        self._browser.close()
                finally:
                    if self._pw_context:
                        self._pw_context.__exit__(*exc)
        self._page = None
        self._context = None
        self._browser = None
        self._pw_context = None

    def _verify_session(self) -> None:
        """Navigate to the POS home page and check we're not redirected to login."""
        page = self.page
        logger.info("Verifying POS session…")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightError as exc:
            raise POSTimeoutError(
                "Could not reach POS portal — check network/VPN"
            ) from exc

        # Give SPA a moment to settle (redirects may be JS-driven)
        time.sleep(3)

        if _is_login_page(page.url):
            raise POSLoginExpiredError(
                "Saved session has expired. "
                "Run `POSSession.interactive_login()` to re-authenticate."
            )
        logger.info("POS session valid — current URL: %s", page.url)

    def screenshot(self, path: str | Path, *, full_page: bool = True) -> Path:
        """Take a screenshot of the current page."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=full_page)
        logger.info("Screenshot saved to %s", path)
        return path

    # ── Interactive login (manual, headful) ──────────────────────────────

    @classmethod
    def interactive_login(
        cls,
        *,
        storage_path: Path = DEFAULT_STORAGE_PATH,
        timeout_s: int = 300,
        har_path: Path | None = None,
        browse_after_login: bool = False,
    ) -> None:
        """Open a visible browser for manual login (QR scan or SMS).

        After successful login, saves the browser storage state to disk.
        This only needs to run once; subsequent sessions reuse the saved state.

        Args:
            storage_path: Where to save the auth state JSON.
            timeout_s: Max seconds to wait for the user to complete login.
            har_path: If set, record all network traffic as a HAR file.
                      Useful for reverse-engineering API endpoints.
            browse_after_login: If True, keep the browser open after login
                      so you can click around (traffic keeps recording).
                      Close the browser manually when done.
        """
        storage_path = Path(storage_path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure Chromium is installed
        cls._ensure_browser()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)

            # Context kwargs — optionally enable HAR recording
            ctx_kwargs: dict[str, Any] = {}
            if har_path:
                har_path = Path(har_path)
                har_path.parent.mkdir(parents=True, exist_ok=True)
                ctx_kwargs["record_har_path"] = str(har_path)
                ctx_kwargs["record_har_url_filter"] = "**/*"
                logger.info("HAR recording enabled → %s", har_path)

            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()

            logger.info("Opening POS login page — please scan QR or enter SMS code")
            print(
                "\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  POS Login — scan QR code or enter SMS in the browser  ║\n"
                "║  The browser will close automatically after login.     ║\n"
                f"║  Timeout: {timeout_s}s                                       ║\n"
                "╚══════════════════════════════════════════════════════════╝\n"
            )

            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)

            # Poll until the URL moves away from the login page
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if not _is_login_page(page.url):
                    # Double-check after a brief settle
                    time.sleep(2)
                    if not _is_login_page(page.url):
                        break
                time.sleep(2)
            else:
                browser.close()
                raise POSTimeoutError(
                    f"Login was not completed within {timeout_s}s"
                )

            # Wait for the SPA to finish loading post-login
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)

            print("\n✅ Login successful!")

            if browse_after_login:
                print(
                    "🔍 Browse around to capture API traffic.\n"
                    "   Close the browser window when you're done."
                )
                # Wait for the browser to be closed manually
                try:
                    page.wait_for_event("close", timeout=timeout_s * 1000)
                except PlaywrightError:
                    pass

            # Save storage state
            context.storage_state(path=str(storage_path))
            logger.info("Storage state saved to %s", storage_path)
            print(f"💾 Session saved to {storage_path}")

            if har_path:
                # Close context to flush HAR
                context.close()
                print(f"📡 HAR traffic log saved to {har_path}")
            else:
                context.close()

            browser.close()
