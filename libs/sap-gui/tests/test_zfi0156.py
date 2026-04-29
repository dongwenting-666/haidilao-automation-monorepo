"""Unit tests for sap_gui.processes.zfi0156 — no SAP GUI required.

Covers pure helpers, constant pinning, the Windows execute() path
(reuses SAPExporter), and the macOS batched-JS builder.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sap_gui.processes.zfi0156 import (
    DEFAULT_PLANT_HIGH,
    DEFAULT_PLANT_LOW,
    EXPORT_MENU_PATH,
    default_filename,
    execute,
    format_sap_text_date,
    previous_month_range,
)


# ── format_sap_text_date ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 2, 1), "2026.02.01"),
        (date(2026, 2, 28), "2026.02.28"),
        (date(2024, 2, 29), "2024.02.29"),
        (date(2026, 3, 5), "2026.03.05"),  # zero-padded
    ],
)
def test_format_sap_text_date(d, expected):
    assert format_sap_text_date(d) == expected


# ── default_filename ───────────────────────────────────────────────────


def test_default_filename_uses_zfi0156_dash_yyyymm_xlsx():
    # The recording showed "zfi0156-202603" as the SAP filename input.
    # We append .xlsx so the file opens directly in Excel.
    assert default_filename(date(2026, 3, 15)) == "zfi0156-202603.xlsx"
    assert default_filename(date(2026, 2, 1)) == "zfi0156-202602.xlsx"
    assert default_filename(date(2025, 12, 31)) == "zfi0156-202512.xlsx"


def test_default_filename_extension_is_xlsx():
    assert default_filename(date(2026, 2, 1)).endswith(".xlsx")


# ── previous_month_range ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "today, want_first, want_last",
    [
        (date(2026, 3, 15), date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 1, 5), date(2025, 12, 1), date(2025, 12, 31)),
        (date(2024, 3, 1), date(2024, 2, 1), date(2024, 2, 29)),  # leap year
        (date(2026, 5, 1), date(2026, 4, 1), date(2026, 4, 30)),
    ],
)
def test_previous_month_range_cases(today, want_first, want_last):
    with patch("sap_gui.processes.zfi0156.date") as fake_date:
        fake_date.today.return_value = today
        fake_date.side_effect = lambda *a, **kw: date(*a, **kw)
        first, last = previous_month_range()
    assert first == want_first
    assert last == want_last


# ── Constants — pin so a refactor can't silently break SAP IDs ────────


def test_default_plant_codes_are_canada_range():
    # CA01-CA09 = Canada plants. Pin so a "cleanup" PR can't switch them.
    assert DEFAULT_PLANT_LOW == "CA01"
    assert DEFAULT_PLANT_HIGH == "CA09"


def test_export_menu_path_is_list_export_spreadsheet():
    # ZFI0156 uses the standard List → Export → Spreadsheet menu, NOT
    # MB5B's System → List → Save → Local File. Pin to catch a
    # copy-paste from the MB5B module.
    assert EXPORT_MENU_PATH == "wnd[0]/mbar/menu[0]/menu[3]/menu[1]"


# ── execute() orchestration with mocked session/nav/exporter ──────────


@pytest.fixture
def mock_session():
    """A bare MagicMock standing in for the SAP COM session."""
    return MagicMock()


@pytest.fixture
def mock_nav():
    return MagicMock()


@pytest.fixture
def mock_exporter(tmp_path):
    """Exporter whose export_list_to_file echoes the requested path."""
    exporter = MagicMock()
    # Return whatever path the caller asked for — simulates a successful save.
    exporter.export_list_to_file.side_effect = lambda p, **_kw: p
    return exporter


def test_execute_navigates_runs_exports(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    output = tmp_path / "out.xlsx"
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=output,
        plant_low="CA01",
        plant_high="CA09",
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    )
    # Transaction
    mock_nav.run_transaction.assert_any_call("ZFI0156")
    # Plants + dates
    field_calls = {c.args[0] for c in mock_nav.set_field.call_args_list}
    assert "wnd[0]/usr/ctxtS_WERKS-LOW" in field_calls
    assert "wnd[0]/usr/ctxtS_WERKS-HIGH" in field_calls
    assert "wnd[0]/usr/ctxtS_BUDAT-LOW" in field_calls
    assert "wnd[0]/usr/ctxtS_BUDAT-HIGH" in field_calls
    # F8
    assert any(c.args == (8,) for c in mock_nav.send_vkey.call_args_list)
    # Export via the exporter (NOT a manual menu select)
    mock_exporter.export_list_to_file.assert_called_once()
    assert mock_exporter.export_list_to_file.call_args.kwargs["menu_path"] == EXPORT_MENU_PATH


def test_execute_passes_dates_in_sap_format(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=tmp_path / "out.xlsx",
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    )
    date_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_BUDAT-LOW"
    )
    date_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_BUDAT-HIGH"
    )
    assert date_low.args[1] == "2026.02.01"
    assert date_high.args[1] == "2026.02.28"


def test_execute_defaults_to_previous_month(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    with patch("sap_gui.processes.zfi0156.date") as fake_date:
        fake_date.today.return_value = date(2026, 3, 15)
        fake_date.side_effect = lambda *a, **kw: date(*a, **kw)
        execute(
            session=mock_session,
            nav=mock_nav,
            exporter=mock_exporter,
            output_path=tmp_path / "out.xlsx",
        )
    date_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_BUDAT-LOW"
    )
    date_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_BUDAT-HIGH"
    )
    assert date_low.args[1] == "2026.02.01"
    assert date_high.args[1] == "2026.02.28"


def test_execute_uses_default_plant_codes(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=tmp_path / "out.xlsx",
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    )
    plant_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_WERKS-LOW"
    )
    plant_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtS_WERKS-HIGH"
    )
    assert plant_low.args[1] == DEFAULT_PLANT_LOW
    assert plant_high.args[1] == DEFAULT_PLANT_HIGH


def test_execute_creates_output_parent_dir(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    nested = tmp_path / "deeply" / "nested" / "dir"
    output = nested / "out.xlsx"
    assert not nested.exists()
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=output,
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    )
    assert nested.exists()


def test_execute_returns_to_session_manager(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    """Always reset to SESSION_MANAGER post-export so the next run
    doesn't inherit a result/save window."""
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=tmp_path / "out.xlsx",
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
    )
    assert any(
        c.args == ("SESSION_MANAGER",)
        for c in mock_nav.run_transaction.call_args_list
    )


def test_execute_propagates_export_timeout(
    mock_session, mock_nav, mock_exporter, tmp_path,
):
    """The export_timeout argument must reach SAPExporter — otherwise
    a slow report will surface as a timeout on the wrong layer."""
    execute(
        session=mock_session,
        nav=mock_nav,
        exporter=mock_exporter,
        output_path=tmp_path / "out.xlsx",
        date_from=date(2026, 2, 1),
        date_to=date(2026, 2, 28),
        export_timeout=42.0,
    )
    assert mock_exporter.export_list_to_file.call_args.kwargs["timeout"] == 42.0


# ── _run_darwin: exercise the JS-builder path with mocked SAPSession ──


def test_run_darwin_builds_js_with_correct_field_ids(tmp_path):
    """The macOS path collapses everything into one execute_js call.
    Pin the JS payload's required fragments."""
    from sap_gui.processes.zfi0156 import _run_darwin

    fake_session_obj = MagicMock()
    fake_session_obj.session.execute_js.return_value = str(tmp_path)

    output = tmp_path / "zfi0156-202602.xlsx"
    (tmp_path / "zfi0156-202602.xlsx").touch()

    with patch("sap_gui.processes.zfi0156.SAPSession") as mock_sap_cls:
        mock_sap_cls.return_value.__enter__.return_value = fake_session_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        _run_darwin(
            username="u", password="p",
            output_path=output,
            plant_low="CA01", plant_high="CA09",
            date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            language="ZH", export_timeout=5.0,
        )

    fake_session_obj.session.execute_js.assert_called_once()
    js_payload = fake_session_obj.session.execute_js.call_args.args[0]

    for fragment in [
        'startTransaction("ZFI0156")',
        "ctxtS_WERKS-LOW",
        "ctxtS_WERKS-HIGH",
        "ctxtS_BUDAT-LOW",
        "ctxtS_BUDAT-HIGH",
        "2026.02.01",
        "2026.02.28",
        "CA01",
        "CA09",
        EXPORT_MENU_PATH,
        "ctxtDY_FILENAME",
        '"zfi0156-202602.xlsx"',
        # No SAPLSPO5 — make sure we didn't accidentally copy MB5B's radio.
    ]:
        assert fragment in js_payload, (
            f"missing fragment in built JS: {fragment!r}"
        )


def test_run_darwin_does_not_select_format_radio(tmp_path):
    """ZFI0156 has NO SAPLSPO5 format dialog. The JS must not include
    the spreadsheet-radio path or it will fail with 'element not found'."""
    from sap_gui.processes.zfi0156 import _run_darwin

    fake_session_obj = MagicMock()
    fake_session_obj.session.execute_js.return_value = str(tmp_path)

    output = tmp_path / "zfi0156-202602.xlsx"
    (tmp_path / "zfi0156-202602.xlsx").touch()

    with patch("sap_gui.processes.zfi0156.SAPSession") as mock_sap_cls:
        mock_sap_cls.return_value.__enter__.return_value = fake_session_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        _run_darwin(
            username="u", password="p",
            output_path=output,
            plant_low="CA01", plant_high="CA09",
            date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
            language="ZH", export_timeout=5.0,
        )

    js_payload = fake_session_obj.session.execute_js.call_args.args[0]
    assert "SAPLSPO5" not in js_payload
    assert "radSPOPLI" not in js_payload


def test_run_darwin_raises_when_dy_path_empty(tmp_path):
    """SAP returning empty DY_PATH = export silently failed; surface it."""
    from sap_gui.processes.zfi0156 import _run_darwin

    fake_session_obj = MagicMock()
    fake_session_obj.session.execute_js.return_value = ""

    from sap_gui.errors import SAPExportError
    with patch("sap_gui.processes.zfi0156.SAPSession") as mock_sap_cls:
        mock_sap_cls.return_value.__enter__.return_value = fake_session_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        with pytest.raises(SAPExportError):
            _run_darwin(
                username="u", password="p",
                output_path=tmp_path / "out.xlsx",
                plant_low="CA01", plant_high="CA09",
                date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
                language="ZH", export_timeout=1.0,
            )


# ── run() platform dispatch ────────────────────────────────────────────


def test_run_dispatches_to_darwin_on_macos(tmp_path):
    from sap_gui.processes import zfi0156 as zfi_mod

    output = tmp_path / "out.xlsx"
    with patch.object(zfi_mod, "sys") as fake_sys, \
         patch.object(zfi_mod, "_run_darwin") as fake_darwin:
        fake_sys.platform = "darwin"
        fake_darwin.return_value = output
        result = zfi_mod.run(
            username="u", password="p",
            output_path=output,
            date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
        )
    assert result == output
    fake_darwin.assert_called_once()


def test_run_dispatches_to_execute_on_windows(tmp_path):
    from sap_gui.processes import zfi0156 as zfi_mod

    output = tmp_path / "out.xlsx"
    fake_sap_obj = MagicMock()
    fake_sap_obj.session = MagicMock()

    with patch.object(zfi_mod, "sys") as fake_sys, \
         patch.object(zfi_mod, "SAPSession") as mock_sap_cls, \
         patch.object(zfi_mod, "execute") as fake_execute:
        fake_sys.platform = "win32"
        mock_sap_cls.return_value.__enter__.return_value = fake_sap_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        fake_execute.return_value = output

        result = zfi_mod.run(
            username="u", password="p",
            output_path=output,
            date_from=date(2026, 2, 1), date_to=date(2026, 2, 28),
        )

    assert result == output
    fake_execute.assert_called_once()
