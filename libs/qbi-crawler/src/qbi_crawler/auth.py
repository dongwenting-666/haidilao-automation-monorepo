"""Quick BI authentication via Playwright browser automation."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Self

from playwright.sync_api import Browser, BrowserContext, Error as PlaywrightError, Page, sync_playwright

from qbi_crawler.constants import BASE_URL
from qbi_crawler.errors import QBILoginError, QBITimeoutError

logger = logging.getLogger(__name__)

LOGIN_URL = f"{BASE_URL}/auth_sso/login/login.htm"

_browser_installed = False
_browser_lock = threading.Lock()


class QBISession:
    """Manages an authenticated Playwright session to Quick BI.

    Usage::

        with QBISession(username="user", password="pass") as session:
            page = session.page
            # navigate, extract data, screenshot, etc.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self.username = username
        self._password: str | None = password
        self.headless = headless
        self.timeout_ms = timeout_ms

        self._pw_context: Any = None  # PlaywrightContextManager (no public type)
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise QBILoginError("Session not started — use as context manager")
        return self._page

    @staticmethod
    def _ensure_browser() -> None:
        """Install Chromium if not already present (skipped after first success)."""
        global _browser_installed
        if _browser_installed:
            return
        with _browser_lock:
            if _browser_installed:  # double-check after acquiring lock
                return
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    capture_output=True,
                )
                _browser_installed = True
            except FileNotFoundError:
                logger.debug("Playwright CLI not found — assuming browser already present")
                _browser_installed = True
            except subprocess.CalledProcessError as exc:
                logger.warning("Browser install returned non-zero: %s", exc)
            except OSError:
                # Covers permission/filesystem issues beyond FileNotFoundError
                logger.warning("OS error during browser install", exc_info=True)

    def __enter__(self) -> Self:
        self._ensure_browser()
        self._pw_context = sync_playwright()
        pw = self._pw_context.start()
        self._browser = pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._login()
        return self

    def __exit__(self, *exc) -> None:
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

    def _login(self) -> None:
        """Navigate to login page, fill LDAP credentials, and submit."""
        if self._password is None:
            raise QBILoginError("Password already consumed — cannot re-login")

        page = self.page
        logger.info("Navigating to QBI login page")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

        try:
            # LDAP login form — wait for the dynamically rendered inputs
            username_input = page.wait_for_selector(
                "input[type='text'], input[name='username'], input[placeholder*='用户'], input[placeholder*='账号']",
                timeout=self.timeout_ms,
            )
            password_input = page.wait_for_selector(
                "input[type='password']",
                timeout=self.timeout_ms,
            )
        except PlaywrightError as exc:
            raise QBITimeoutError(
                "Login form did not render — check network connectivity"
            ) from exc

        if not username_input or not password_input:
            raise QBITimeoutError("Login form inputs not found")

        logger.info("Filling login credentials for %s", self.username)
        username_input.fill(self.username)
        password_input.fill(self._password)
        self._password = None  # clear credentials after use

        # Click submit button
        submit = page.wait_for_selector(
            "button[type='submit'], button.login-btn, button:has-text('登录'), button:has-text('Login')",
            timeout=self.timeout_ms,
        )
        if not submit:
            raise QBITimeoutError("Login submit button not found")
        submit.click()

        # Wait for navigation away from login page
        try:
            page.wait_for_url(
                lambda url: "/auth_sso/login" not in url,
                timeout=self.timeout_ms,
                wait_until="domcontentloaded",
            )
        except PlaywrightError as exc:
            raise QBILoginError(
                "Login failed — check username/password"
            ) from exc

        # Wait for the portal to finish loading
        page.wait_for_load_state("domcontentloaded")
        logger.info("Login successful")

    def screenshot(self, path: str | Path, *, full_page: bool = True) -> Path:
        """Take a screenshot of the current page."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=full_page)
        logger.info("Screenshot saved to %s", path)
        return path
