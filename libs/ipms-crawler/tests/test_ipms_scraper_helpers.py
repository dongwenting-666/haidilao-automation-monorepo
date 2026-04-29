"""Scraper-flow tests with a mocked Playwright Page.

We don't try to test the JS-eval bodies (those need a real browser); we
test that ``download_bom`` orchestrates its helpers in the correct order,
hands off the right arguments, and surfaces the right errors.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ipms_crawler.errors import IPMSExportError
from ipms_crawler.scraper import (
    BOM_URL,
    download_bom,
)


@pytest.fixture
def fake_session():
    """A MagicMock that quacks like an IPMSSession context manager."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.page = MagicMock()
    return session


@pytest.fixture
def patched_session(fake_session):
    """Patch IPMSSession class to return the fake_session instance."""
    with patch(
        "ipms_crawler.scraper.IPMSSession", return_value=fake_session
    ) as cls:
        yield cls, fake_session


def test_download_bom_navigates_to_bom_url(patched_session, tmp_path):
    cls, session = patched_session
    # Stub the per-tab worker so we don't need real DOM interactions.
    with patch(
        "ipms_crawler.scraper._export_one_tab",
        return_value=tmp_path / "x.xlsx",
    ):
        download_bom(
            output_dir=tmp_path,
            tabs=("菜品",),
            skip_vpn=True,
        )
    # The session must navigate to BOM_URL once before per-tab work.
    session.page.goto.assert_called_once()
    args, kwargs = session.page.goto.call_args
    assert args[0] == BOM_URL


def test_download_bom_runs_each_tab_in_order(patched_session, tmp_path):
    cls, session = patched_session
    seen_tabs: list[str] = []

    def fake_export(*, page, tab, region, output_dir):
        seen_tabs.append(tab)
        return output_dir / f"{tab}.xlsx"

    with patch(
        "ipms_crawler.scraper._export_one_tab", side_effect=fake_export
    ):
        download_bom(
            output_dir=tmp_path,
            tabs=("菜品", "锅底"),
            skip_vpn=True,
        )
    assert seen_tabs == ["菜品", "锅底"]


def test_download_bom_creates_output_dir(patched_session, tmp_path):
    out = tmp_path / "nested" / "ipms"
    assert not out.exists()
    with patch(
        "ipms_crawler.scraper._export_one_tab",
        return_value=out / "x.xlsx",
    ):
        download_bom(output_dir=out, tabs=("菜品",), skip_vpn=True)
    assert out.exists()


def test_download_bom_passes_region_to_helper(patched_session, tmp_path):
    cls, session = patched_session
    with patch(
        "ipms_crawler.scraper._export_one_tab",
        return_value=tmp_path / "x.xlsx",
    ) as mock_export:
        download_bom(
            output_dir=tmp_path,
            tabs=("菜品",),
            region="美国",
            skip_vpn=True,
        )
    assert mock_export.call_args.kwargs["region"] == "美国"


def test_download_bom_propagates_skip_vpn_to_session(
    patched_session, tmp_path
):
    cls, session = patched_session
    with patch(
        "ipms_crawler.scraper._export_one_tab",
        return_value=tmp_path / "x.xlsx",
    ):
        download_bom(
            output_dir=tmp_path,
            tabs=("菜品",),
            skip_vpn=True,
            headless=False,
        )
    assert cls.call_args.kwargs["skip_vpn"] is True
    assert cls.call_args.kwargs["headless"] is False


def test_download_bom_screenshots_on_helper_failure(
    patched_session, tmp_path
):
    """When _export_one_tab raises, we should snapshot the page so the
    operator has something to debug against."""
    cls, session = patched_session
    with patch(
        "ipms_crawler.scraper._export_one_tab",
        side_effect=IPMSExportError("export blew up"),
    ):
        with pytest.raises(IPMSExportError):
            download_bom(
                output_dir=tmp_path,
                tabs=("菜品",),
                skip_vpn=True,
            )
    # We expect at least one screenshot to have been requested.
    assert session.page.screenshot.call_count >= 1


def test_download_bom_returns_paths_in_call_order(
    patched_session, tmp_path
):
    cls, session = patched_session
    paths = [tmp_path / "a.xlsx", tmp_path / "b.xlsx"]

    def fake_export(*, page, tab, region, output_dir):
        return paths.pop(0)

    with patch(
        "ipms_crawler.scraper._export_one_tab", side_effect=fake_export
    ):
        result = download_bom(
            output_dir=tmp_path,
            tabs=("菜品", "锅底"),
            skip_vpn=True,
        )
    assert result == [tmp_path / "a.xlsx", tmp_path / "b.xlsx"]


def test_download_bom_swallows_spa_aborted_navigation(
    patched_session, tmp_path
):
    """The BOM SPA hijacks navigation, causing goto to raise ERR_ABORTED.
    The scraper recognizes this string and continues; any other goto
    error must propagate."""
    from playwright.sync_api import Error as PlaywrightError

    cls, session = patched_session
    session.page.goto.side_effect = PlaywrightError(
        "Page.goto: net::ERR_ABORTED at " + BOM_URL
    )

    with patch(
        "ipms_crawler.scraper._export_one_tab",
        return_value=tmp_path / "x.xlsx",
    ):
        download_bom(
            output_dir=tmp_path,
            tabs=("菜品",),
            skip_vpn=True,
        )
    # Even though goto raised, the per-tab work still runs.
    session.page.wait_for_selector.assert_called()


def test_download_bom_re_raises_unknown_goto_errors(
    patched_session, tmp_path
):
    from playwright.sync_api import Error as PlaywrightError

    cls, session = patched_session
    session.page.goto.side_effect = PlaywrightError(
        "Page.goto: net::ERR_CONNECTION_RESET"
    )
    with patch("ipms_crawler.scraper._export_one_tab"):
        with pytest.raises(PlaywrightError):
            download_bom(
                output_dir=tmp_path,
                tabs=("菜品",),
                skip_vpn=True,
            )
