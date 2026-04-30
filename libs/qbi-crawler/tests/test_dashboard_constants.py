"""Tests for qbi_crawler.dashboard — constant pinning and helpers that
don't require a real browser.

The full navigate/query/export flow is exercised by live runs against
the QBI portal; here we just pin the public surface so a refactor can't
silently drop a report or rename a constant.
"""

from __future__ import annotations

import pytest

from qbi_crawler import dashboard


# ── Public surface ────────────────────────────────────────────────────


def test_overseas_set_meal_report_constant_exists():
    # Newly added 2026-04-29; must be exported from the package root too.
    from qbi_crawler import REPORT_OVERSEAS_SET_MEAL

    assert REPORT_OVERSEAS_SET_MEAL == "海外套餐销售明细"
    assert dashboard.REPORT_OVERSEAS_SET_MEAL == REPORT_OVERSEAS_SET_MEAL


def test_set_country_is_exported_from_package_root():
    # set_country is the new helper for reports with a 国家 dropdown
    # (海外套餐销售明细). If the export goes missing, the consuming
    # project's import fails at startup, not at run time — pin it.
    from qbi_crawler import set_country

    assert callable(set_country)
    assert set_country is dashboard.set_country


# ── Menu/page-id mappings ─────────────────────────────────────────────


def test_existing_report_menu_ids_unchanged():
    # The three pre-existing reports' IDs are load-bearing for the
    # daily-report cron and ad-hoc consumers. Pin them so a "cleanup"
    # PR can't quietly rotate the values.
    assert dashboard._REPORT_MENU_IDS[dashboard.REPORT_DAILY] == \
        "89809ff6-a4fe-4fd7-853d-49315e51b2ec"
    assert dashboard._REPORT_MENU_IDS[dashboard.REPORT_TIME_PERIOD] == \
        "4ee6d680-5b6c-4b35-ac8f-b9851be038da"
    assert dashboard._REPORT_MENU_IDS[dashboard.REPORT_24H] == \
        "2090b625-1a31-4dcb-adc8-f4e5b7d33339"


def test_overseas_set_meal_has_menu_and_page_id_entries():
    # The new report must be registered in BOTH dicts so navigate_to_report
    # picks the fast pageId-based URL. Existence is the only thing pinned
    # here; the actual values come from a live discovery run and may
    # change if the QBI admins rebuild the dashboard.
    assert dashboard.REPORT_OVERSEAS_SET_MEAL in dashboard._REPORT_MENU_IDS
    assert dashboard.REPORT_OVERSEAS_SET_MEAL in dashboard._REPORT_PAGE_IDS


def test_overseas_set_meal_ids_are_real_uuids():
    """Discovered live 2026-04-29 and verified via verify_qbi_ids.py
    (body header reads '海外套餐销售明细'). Pin both values so a future
    'cleanup' PR can't silently swap them and break the cron."""
    assert dashboard._REPORT_MENU_IDS[dashboard.REPORT_OVERSEAS_SET_MEAL] == \
        "3a4a0da7-f754-4b79-a662-5b49def5b716"
    assert dashboard._REPORT_PAGE_IDS[dashboard.REPORT_OVERSEAS_SET_MEAL] == \
        "55c5d6ee-297c-44ad-842c-51e2a279c690"


# ── download_report() arg-passthrough ─────────────────────────────────


def test_download_report_passes_country_through(monkeypatch, tmp_path):
    """The new ``country`` kwarg must reach ``set_date_range`` — without
    it, REPORT_OVERSEAS_SET_MEAL would silently export ALL countries.
    Mock both navigate and set_date_range so we can assert the kwarg
    landed correctly without touching a real browser."""
    seen: dict[str, object] = {}

    def fake_navigate(page, report_name):
        seen["report_name"] = report_name
        return "FAKE_IFRAME"

    def fake_set_date_range(iframe, start, end, *, country=None):
        seen["iframe"] = iframe
        seen["start"] = start
        seen["end"] = end
        seen["country"] = country

    def fake_export(iframe, download_dir):
        seen["export_iframe"] = iframe
        seen["download_dir"] = download_dir
        return tmp_path / "out.xlsx"

    monkeypatch.setattr(dashboard, "navigate_to_report", fake_navigate)
    monkeypatch.setattr(dashboard, "set_date_range", fake_set_date_range)
    monkeypatch.setattr(dashboard, "export_excel", fake_export)

    out = dashboard.download_report(
        page=object(),  # never used
        report_name=dashboard.REPORT_OVERSEAS_SET_MEAL,
        start_date="2026-03-01",
        end_date="2026-03-31",
        download_dir=tmp_path,
        country="加拿大",
    )

    assert out == tmp_path / "out.xlsx"
    assert seen["report_name"] == dashboard.REPORT_OVERSEAS_SET_MEAL
    assert seen["iframe"] == "FAKE_IFRAME"
    assert seen["start"] == "2026-03-01"
    assert seen["end"] == "2026-03-31"
    assert seen["country"] == "加拿大"


def test_download_report_country_defaults_to_none(monkeypatch, tmp_path):
    """For the existing reports (REPORT_DAILY etc.) we never want a
    country filter applied — confirm omitting the kwarg results in
    None being passed downstream."""
    seen: dict[str, object] = {}

    monkeypatch.setattr(dashboard, "navigate_to_report", lambda p, r: "I")
    monkeypatch.setattr(
        dashboard, "set_date_range",
        lambda iframe, s, e, *, country=None: seen.update(country=country),
    )
    monkeypatch.setattr(dashboard, "export_excel", lambda i, d: tmp_path / "x.xlsx")

    dashboard.download_report(
        page=object(),
        report_name=dashboard.REPORT_DAILY,
        start_date="2026-03-01",
        end_date="2026-03-31",
        download_dir=tmp_path,
    )
    assert seen["country"] is None


def test_download_report_validates_date_order(tmp_path):
    """start_date > end_date must raise QBIError before any browser work
    — guards against a transposed-args caller."""
    from qbi_crawler.errors import QBIError

    with pytest.raises(QBIError):
        dashboard.download_report(
            page=object(),
            report_name=dashboard.REPORT_DAILY,
            start_date="2026-03-31",
            end_date="2026-03-01",
            download_dir=tmp_path,
        )
