"""SAP Fiori login (sgpfioriweb.superhi-tech.com).

Why retries
-----------
The Fiori login flow is observably flaky: the same correct credentials
sometimes get rejected on the first attempt and accepted on the second or
third. We retry up to ``LOGIN_MAX_ATTEMPTS`` times by reloading the page
and refilling the form before giving up.

Credential format
-----------------
Per-store credentials live in the ``SGPFIORIWEB_CREDS`` env var as a JSON
dict mapping store-key → password::

    {"CA8DKG": "hdl001", "CA9DKG": "hdl001", ...}

The store key is also the SAP user name. Client is constant ("800") for
every store.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
    sync_playwright,
)

from sap_fiori_crawler.constants import (
    CREDS_ENV_VAR,
    DEFAULT_CLIENT,
    LAUNCHPAD_URL,
    LOGIN_MAX_ATTEMPTS,
)
from sap_fiori_crawler.errors import FioriLoginError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoreCreds:
    """Per-store SAP credentials."""

    user: str
    password: str
    client: str = DEFAULT_CLIENT


def load_store_creds(store_key: str, env: dict[str, str] | None = None) -> StoreCreds:
    """Read SGPFIORIWEB_CREDS env var and return creds for ``store_key``.

    The store key doubles as the SAP user name.
    """
    env = env if env is not None else os.environ  # type: ignore[assignment]
    raw = env.get(CREDS_ENV_VAR)
    if not raw:
        raise FioriLoginError(
            f"{CREDS_ENV_VAR} env var is not set — cannot look up credentials"
        )
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FioriLoginError(
            f"{CREDS_ENV_VAR} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(mapping, dict):
        raise FioriLoginError(
            f"{CREDS_ENV_VAR} must be a JSON object, got {type(mapping).__name__}"
        )
    pwd = mapping.get(store_key)
    if not pwd:
        raise FioriLoginError(
            f"No password for store {store_key!r} in {CREDS_ENV_VAR}"
        )
    return StoreCreds(user=store_key, password=str(pwd))


def _is_logged_in(page: Page) -> bool:
    """The launchpad title is the store name (e.g. '加拿大八店') after login;
    the login screen title is '登录'."""
    try:
        title = page.title() or ""
    except PlaywrightError:
        return False
    return bool(title) and "登录" not in title


def _fill_login_form(page: Page, creds: StoreCreds) -> None:
    page.locator('input[name="sap-user"]').first.wait_for(
        state="visible", timeout=15_000
    )
    time.sleep(0.5)

    def _retype(selector: str, value: str) -> None:
        field = page.locator(selector).first
        field.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        field.type(value, delay=40)

    _retype('input[name="sap-client"]', creds.client)
    _retype('input[name="sap-user"]', creds.user)
    _retype('input[name="sap-password"]', creds.password)
    page.keyboard.press("Enter")


def login(page: Page, creds: StoreCreds, *, max_attempts: int = LOGIN_MAX_ATTEMPTS) -> None:
    """Drive the SAP login form. Retries on failure (login is flaky)."""
    page.goto(LAUNCHPAD_URL, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        logger.info("Fiori login attempt %d/%d (user=%s)", attempt, max_attempts, creds.user)
        try:
            _fill_login_form(page, creds)
        except PlaywrightError as exc:
            last_error = exc
            logger.warning("login form fill failed: %s", exc)
        else:
            for _ in range(15):
                time.sleep(1)
                if _is_logged_in(page):
                    logger.info("✅ Fiori login succeeded on attempt %d", attempt)
                    return
        # Reload and try again.
        try:
            page.reload(wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
        except PlaywrightError as exc:
            last_error = exc
            logger.warning("reload after failed login raised: %s", exc)

    raise FioriLoginError(
        f"Login failed after {max_attempts} attempts for user {creds.user}"
    ) from last_error


@contextmanager
def fiori_session(
    creds: StoreCreds,
    *,
    headless: bool = False,
    viewport: tuple[int, int] = (1600, 1000),
) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    """Open a Playwright browser, log in, yield (browser, ctx, page).

    Headless defaults to False because the Fiori login is flaky and easier
    to debug visually; flip to True for unattended runs.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            accept_downloads=True,
        )
        page = ctx.new_page()
        try:
            login(page, creds)
            yield browser, ctx, page
        finally:
            try:
                ctx.close()
            finally:
                browser.close()
