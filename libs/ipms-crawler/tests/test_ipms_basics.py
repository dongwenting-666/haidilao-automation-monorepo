"""Sanity tests for the ipms-crawler library — no browser required.

Covers: package exports, URL/path constants, the error hierarchy, the
login-page detector, and the filename-collision helper. These are the
pieces we can verify without spinning up Playwright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipms_crawler import (
    BASE_URL,
    BOM_URL,
    DEFAULT_STORAGE_PATH,
    IPMSError,
    IPMSExportError,
    IPMSLoginExpiredError,
    IPMSSession,
    IPMSTimeoutError,
)
from ipms_crawler.auth import _is_login_page
from ipms_crawler.constants import (
    DEFAULT_OUTPUT_DIR,
    LOGIN_URL,
    TARGET_ROLE,
)
from ipms_crawler.scraper import (
    DEFAULT_REGION,
    DEFAULT_TABS,
    TAB_DISHES,
    TAB_HOTPOT_BASE,
    _unique_path,
)


# ── Constants ──────────────────────────────────────────────────────────


def test_base_url_is_https_internal_host():
    assert BASE_URL.startswith("https://")
    assert "superhi-tech.com" in BASE_URL


def test_login_url_descends_from_base():
    assert LOGIN_URL.startswith(BASE_URL)
    assert LOGIN_URL.endswith("/login")


def test_bom_url_targets_overseas_bom_list():
    # Hardcoded path — if the IPMS team renames the route this breaks
    # immediately rather than failing silently mid-scrape.
    assert BOM_URL == f"{BASE_URL}/approval/bomMgt/overseasBomList"


def test_storage_path_does_not_collide_with_pos_crawler():
    # Both crawlers share ~/.haidilao/ — the file basename must differ
    # so reusing one session doesn't poison the other.
    assert DEFAULT_STORAGE_PATH.parent == Path.home() / ".haidilao"
    assert DEFAULT_STORAGE_PATH.name == "ipms-storage-state.json"
    assert "pos" not in DEFAULT_STORAGE_PATH.name


def test_output_dir_default_is_relative():
    # Resolved at runtime against CWD — same shape as `output/qbi/` for
    # the QBI crawler.
    assert DEFAULT_OUTPUT_DIR == Path("output/ipms")


def test_target_role_is_business_analyst():
    # If someone changes the value, an IPMS admin probably renamed the
    # role and we need a follow-up. Pin it so the change is intentional.
    assert TARGET_ROLE == "00 业务分析岗"


def test_default_tabs_match_user_request():
    # User asked for 菜品 + 锅底 (skipping 非标规格菜品). Pin so a
    # well-meaning refactor can't quietly drop one.
    assert DEFAULT_TABS == (TAB_DISHES, TAB_HOTPOT_BASE) == ("菜品", "锅底")


def test_default_region_is_canada():
    assert DEFAULT_REGION == "加拿大"


def test_session_class_is_exported():
    # Public surface: a caller importing from the package root must
    # receive the same class as the auth module. Catches name typos in
    # __init__.py.
    from ipms_crawler.auth import IPMSSession as _Direct

    assert IPMSSession is _Direct


# ── Error hierarchy ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc_cls",
    [IPMSLoginExpiredError, IPMSTimeoutError, IPMSExportError],
)
def test_concrete_errors_descend_from_ipms_error(exc_cls):
    # All concrete errors must descend from IPMSError so callers can
    # catch one base. Tested explicitly because it's the public contract.
    assert issubclass(exc_cls, IPMSError)


@pytest.mark.parametrize(
    "exc_cls",
    [IPMSLoginExpiredError, IPMSTimeoutError, IPMSExportError],
)
def test_concrete_errors_can_be_raised(exc_cls):
    with pytest.raises(IPMSError):
        raise exc_cls("boom")


# ── _is_login_page ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://ipms-global.superhi-tech.com/login",
        "https://ipms-global.superhi-tech.com/login?redirect=%2Fapproval",
        "https://ipms-global.superhi-tech.com/Login",  # case-insensitive
    ],
)
def test_is_login_page_matches_login_paths(url):
    assert _is_login_page(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://ipms-global.superhi-tech.com/myMessage",
        "https://ipms-global.superhi-tech.com/approval/bomMgt/overseasBomList",
        "https://ipms-global.superhi-tech.com/",
    ],
)
def test_is_login_page_does_not_match_logged_in_paths(url):
    assert not _is_login_page(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://ipms-global.superhi-tech.com/sso/callback",
        "https://ipms-global.superhi-tech.com/auth/lark",
    ],
)
def test_sso_and_auth_paths_are_not_login_pages(url):
    # Used to be flagged as login (false positive), which broke the
    # post-QR redirect detection. Regression guard: leave alone.
    assert not _is_login_page(url)


# ── _unique_path ───────────────────────────────────────────────────────


def test_unique_path_returns_target_when_free(tmp_path):
    target = tmp_path / "foo.xlsx"
    assert _unique_path(target) == target


def test_unique_path_appends_counter_on_first_collision(tmp_path):
    (tmp_path / "foo.xlsx").touch()
    assert _unique_path(tmp_path / "foo.xlsx") == tmp_path / "foo_1.xlsx"


def test_unique_path_walks_past_existing_counters(tmp_path):
    (tmp_path / "foo.xlsx").touch()
    (tmp_path / "foo_1.xlsx").touch()
    (tmp_path / "foo_2.xlsx").touch()
    assert _unique_path(tmp_path / "foo.xlsx") == tmp_path / "foo_3.xlsx"


def test_unique_path_preserves_extension_and_stem(tmp_path):
    # The download server emits names like 海外菜品物料明细_20260429_xxx.xlsx
    # — colliding only when re-running within the same minute. We must
    # keep the .xlsx extension so the OS still opens it in Excel.
    name = "海外菜品物料明细_20260429_01_51_37.xlsx"
    (tmp_path / name).touch()
    result = _unique_path(tmp_path / name)
    assert result.suffix == ".xlsx"
    assert result.stem.endswith("_1")
    assert result.name.startswith("海外菜品物料明细_20260429_01_51_37")
