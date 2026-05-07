"""IPMS authentication via Playwright with persistent browser storage state.

Login flow:
  1. First time / expired: launch headful browser, user scans Lark QR.
     Storage state is saved to disk after a successful login.
  2. Subsequent runs: load saved storage state, verify session is alive,
     proceed headlessly.

Auto-connects CorpLink VPN before any browser work — IPMS is reachable
only over the corporate VPN.
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

from ipms_crawler.constants import (
    BASE_URL,
    DEFAULT_STORAGE_PATH,
    LOGIN_URL,
    TARGET_ROLE,
)
from ipms_crawler.errors import IPMSLoginExpiredError, IPMSTimeoutError
from vpn import ensure_vpn

logger = logging.getLogger(__name__)

_browser_installed = False
_browser_lock = threading.Lock()

# Only `/login` counts as the login page. The Lark-OAuth callback may
# briefly transit through other paths but those are not login UI.
_LOGIN_PATH_FRAGMENTS = ("/login",)

# A selector that only exists once the SPA has finished post-login boot.
# 我的工作台 is the first item in the top nav (see CLAUDE-side screenshots).
POST_LOGIN_SELECTOR = "text=我的工作台"


def _is_login_page(url: str) -> bool:
    from urllib.parse import urlparse

    path = urlparse(url).path.lower()
    return any(frag in path for frag in _LOGIN_PATH_FRAGMENTS)


class IPMSSession:
    """Manages a Playwright session to the Haidilao IPMS portal.

    Calls ``ensure_vpn()`` on entry. Uses saved browser storage state for auth.
    If state is missing/expired, raises IPMSLoginExpiredError with instructions
    to run interactive_login().
    """

    def __init__(
        self,
        *,
        storage_path: Path = DEFAULT_STORAGE_PATH,
        headless: bool = True,
        timeout_ms: int = 30_000,
        skip_vpn: bool = False,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.skip_vpn = skip_vpn

        self._pw_context: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise IPMSLoginExpiredError("Session not started — use as context manager")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise IPMSLoginExpiredError("Session not started — use as context manager")
        return self._context

    @staticmethod
    def _ensure_browser() -> None:
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
            raise IPMSLoginExpiredError(
                f"No saved session at {self.storage_path}. "
                "Run `IPMSSession.interactive_login()` first to authenticate."
            )

        if not self.skip_vpn:
            logger.info("Ensuring CorpLink VPN is connected…")
            ensure_vpn()

        self._ensure_browser()
        self._pw_context = sync_playwright()
        pw = self._pw_context.start()
        self._browser = pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            storage_state=str(self.storage_path),
            accept_downloads=True,
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

        self._verify_session()
        self._switch_role()
        return self

    def __exit__(self, *exc: object) -> None:
        try:
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
        page = self.page
        logger.info("Verifying IPMS session…")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightError as exc:
            raise IPMSTimeoutError(
                "Could not reach IPMS portal — check VPN/network"
            ) from exc

        # Wait for the post-login nav to appear, OR the URL to land on a
        # non-login path. Either signals an active session.
        try:
            page.wait_for_selector(POST_LOGIN_SELECTOR, timeout=15_000, state="visible")
        except PlaywrightError as exc:
            if _is_login_page(page.url):
                raise IPMSLoginExpiredError(
                    "Saved session has expired. "
                    "Run `IPMSSession.interactive_login()` to re-authenticate."
                ) from exc
            # URL is not a login page but the post-login UI didn't load.
            # Could be a one-off render hiccup; let downstream code error
            # with a more specific message.
            logger.warning("Post-login selector not visible at %s", page.url)
        logger.info("IPMS session valid — current URL: %s", page.url)

    def _switch_role(self) -> None:
        """Ensure the active role is ``TARGET_ROLE`` (``00 业务分析岗``).

        The role switcher is an Element-UI ``<el-select>`` in the top right.
        Its current value lives in an ``<input value=...>``, so we identify
        it by scanning visible ``.el-select`` widgets for an input whose
        ``value`` matches a known role pattern.
        """
        page = self.page
        target = TARGET_ROLE

        # Let the SPA finish hydrating before poking the header.
        time.sleep(2)

        # Locate the role-switcher el-select by scanning for one whose input
        # value matches a known role pattern. Tag it so Playwright can find
        # it by attribute selector.
        result = page.evaluate(
            """
            (target) => {
                const selects = Array.from(document.querySelectorAll('.el-select'));
                for (const sel of selects) {
                    const r = sel.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const inp = sel.querySelector('input');
                    if (!inp) continue;
                    const v = inp.value || '';
                    if (v === target) {
                        return {status: 'already-on-target'};
                    }
                    if (/(税率配置|分析岗|管理员|.*岗)/.test(v)) {
                        sel.setAttribute('data-ipms-pw', 'role-select');
                        return {status: 'tagged', currentValue: v};
                    }
                }
                return {status: 'no-select-found'};
            }
            """,
            target,
        )
        logger.debug("Role-select lookup: %s", result)
        status = (result or {}).get("status")
        if status == "already-on-target":
            logger.info("Already on role %s", target)
            return
        if status != "tagged":
            screenshot = self.storage_path.parent / "ipms-role-switch-failed.png"
            try:
                page.screenshot(path=str(screenshot), full_page=True)
            except PlaywrightError:
                pass
            raise IPMSTimeoutError(
                f"Could not find role-switcher: {result}. See {screenshot}"
            )

        # Click the wrapper — Element UI's el-select reliably opens on click.
        page.locator(
            "[data-ipms-pw='role-select'] .el-select__wrapper, "
            "[data-ipms-pw='role-select'] .el-input, "
            "[data-ipms-pw='role-select']"
        ).first.click(timeout=10_000)

        # Wait for the dropdown option containing the target role.
        page.wait_for_function(
            """target => {
                const items = Array.from(document.querySelectorAll(
                    '.el-select-dropdown__item'
                ));
                return items.some(el => {
                    if ((el.textContent || '').trim() !== target) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                });
            }""",
            arg=target,
            timeout=8_000,
        )

        # Click the option using a CSS+text locator.
        page.locator(
            ".el-select-dropdown__item", has_text=target
        ).first.click(timeout=10_000)

        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        logger.info("Role switched to %s", target)

    def screenshot(self, path: str | Path, *, full_page: bool = True) -> Path:
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
        skip_vpn: bool = False,
    ) -> None:
        """Open a visible browser for manual QR-code login.

        After successful login, saves the browser storage state to disk.
        """
        storage_path = Path(storage_path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        if not skip_vpn:
            logger.info("Ensuring CorpLink VPN is connected…")
            ensure_vpn()

        cls._ensure_browser()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)

            ctx_kwargs: dict[str, Any] = {"accept_downloads": True}
            if har_path:
                har_path = Path(har_path)
                har_path.parent.mkdir(parents=True, exist_ok=True)
                ctx_kwargs["record_har_path"] = str(har_path)
                ctx_kwargs["record_har_url_filter"] = "**/*"
                logger.info("HAR recording enabled → %s", har_path)

            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()

            logger.info("Opening IPMS login page — please scan the QR code")
            print(
                "\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  IPMS Login — scan the QR code with Lark in the browser  ║\n"
                "║  The browser will save state automatically after login.  ║\n"
                f"║  Timeout: {timeout_s}s                                       ║\n"
                "╚══════════════════════════════════════════════════════════╝\n"
            )

            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

            # Login is detected when the post-login UI appears
            # (我的工作台 in the top nav) AND the URL has left /login.
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    page.wait_for_selector(
                        POST_LOGIN_SELECTOR,
                        timeout=2000,
                        state="visible",
                    )
                    if not _is_login_page(page.url):
                        break
                except PlaywrightError:
                    pass
                time.sleep(1)
            else:
                browser.close()
                raise IPMSTimeoutError(
                    f"Login was not completed within {timeout_s}s "
                    f"(URL={page.url!r}). "
                    "Did you scan the QR in this Chromium window?"
                )

            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)

            print(f"\n✅ Login successful! URL={page.url}")

            if browse_after_login:
                print(
                    "🔍 Browse around to capture API traffic.\n"
                    "   Close the browser window when you're done."
                )
                try:
                    page.wait_for_event("close", timeout=timeout_s * 1000)
                except PlaywrightError:
                    pass

            context.storage_state(path=str(storage_path))
            logger.info("Storage state saved to %s", storage_path)
            print(f"💾 Session saved to {storage_path}")

            if har_path:
                context.close()
                print(f"📡 HAR traffic log saved to {har_path}")
            else:
                context.close()

            browser.close()
