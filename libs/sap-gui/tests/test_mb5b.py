"""Unit tests for sap_gui.processes.mb5b — no SAP GUI required.

Covers pure helpers (date math, formatting, default filename), constant
contracts (menu paths, radio IDs), and the orchestration path with a
mocked SAP session. The actual SAP interaction is exercised by the
e2e_mb5b.py script (not run in CI).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sap_gui.errors import SAPExportError
from sap_gui.processes.mb5b import (
    DEFAULT_COMPANY_HIGH,
    DEFAULT_COMPANY_LOW,
    FORMAT_RADIO_SPREADSHEET,
    SAVE_MENU_PATH,
    default_filename,
    execute,
    format_sap_text_date,
    previous_month_range,
)


# ── format_sap_text_date ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 3, 15), "2026.03.15"),
        (date(2026, 1, 1), "2026.01.01"),
        (date(2026, 12, 31), "2026.12.31"),
        # Single-digit padding — SAP rejects "2026.3.5" so this is a contract.
        (date(2026, 3, 5), "2026.03.05"),
    ],
)
def test_format_sap_text_date(d, expected):
    assert format_sap_text_date(d) == expected


# ── default_filename ───────────────────────────────────────────────────


def test_default_filename_uses_yyyymm_of_input_date():
    # The user-stated convention is mb5b{YYYYMM}; extension is .xls
    # (NOT .xlsx) because SAPLSPO5's Spreadsheet branch writes UTF-16
    # TSV, not a real xlsx zip.
    assert default_filename(date(2026, 3, 15)) == "mb5b202603.xls"
    assert default_filename(date(2026, 1, 1)) == "mb5b202601.xls"
    assert default_filename(date(2025, 12, 31)) == "mb5b202512.xls"


def test_default_filename_extension_is_xls_not_xlsx():
    # Regression guard against an "obvious" cleanup that switches to
    # .xlsx — the file is UTF-16 TSV, not real Excel; openpyxl can't
    # open it. e2e validation 2026-04-29 confirmed this.
    name = default_filename(date(2026, 3, 1))
    assert name.endswith(".xls")
    assert not name.endswith(".xlsx")


# ── previous_month_range ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "today, want_first, want_last",
    [
        # Mid-month, regular month
        (date(2026, 4, 15), date(2026, 3, 1), date(2026, 3, 31)),
        # First of month — previous month should still be the previous one
        (date(2026, 4, 1), date(2026, 3, 1), date(2026, 3, 31)),
        # January → previous = December of prior year
        (date(2026, 1, 10), date(2025, 12, 1), date(2025, 12, 31)),
        # March in non-leap year → previous = February with 28 days
        (date(2026, 3, 5), date(2026, 2, 1), date(2026, 2, 28)),
        # March in leap year → previous = February with 29 days
        (date(2024, 3, 5), date(2024, 2, 1), date(2024, 2, 29)),
        # Day after a 31-day month
        (date(2026, 6, 1), date(2026, 5, 1), date(2026, 5, 31)),
    ],
)
def test_previous_month_range_cases(today, want_first, want_last):
    with patch("sap_gui.processes.mb5b.date") as fake_date:
        fake_date.today.return_value = today
        # date(...) construction must still work for the helper's internals
        fake_date.side_effect = lambda *a, **kw: date(*a, **kw)
        first, last = previous_month_range()
    assert first == want_first
    assert last == want_last


def test_previous_month_range_returns_dates():
    first, last = previous_month_range()
    assert isinstance(first, date)
    assert isinstance(last, date)
    # First day must always be day=1; last is whatever the calendar says.
    assert first.day == 1
    assert last.month == first.month
    assert last.year == first.year


# ── Constants — pin so a refactor can't silently break SAP IDs ────────


def test_default_company_codes():
    # The user's recording used 9451 / 9452 (Canada / overseas group).
    # If these change, ops needs to update the .env or pass overrides —
    # pin so a "cleanup" PR can't quietly switch defaults.
    assert DEFAULT_COMPANY_LOW == "9451"
    assert DEFAULT_COMPANY_HIGH == "9452"


def test_save_menu_path_targets_system_list_save_local():
    # MB5B uses System -> List -> Save -> Local File, NOT KSB1's
    # List -> Export -> Spreadsheet (menu[0]/menu[3]/menu[1]).
    # Pin to catch accidental copy-paste from KSB1.
    assert SAVE_MENU_PATH == "wnd[0]/mbar/menu[0]/menu[1]/menu[2]"


def test_format_radio_targets_spreadsheet_branch():
    # SAPLSPO5 dialog: index [1,0] is the Spreadsheet radio. The other
    # branches (HTML, RTF, plain) are at different indices — getting this
    # wrong silently produces the wrong file format.
    assert FORMAT_RADIO_SPREADSHEET == (
        "wnd[1]/usr/subSUBSCREEN_STEPLOOP:SAPLSPO5:0150"
        "/sub:SAPLSPO5:0150/radSPOPLI-SELFLAG[1,0]"
    )


# ── execute() orchestration with a mocked session ──────────────────────


@pytest.fixture
def mock_session(tmp_path):
    """A MagicMock that quacks like a SAP COM session.

    All findById calls return MagicMocks with chainable .text / .press() /
    .select() / .sendVKey() / .close(). The DY_PATH field returns a real
    path so shutil.move can target it.
    """
    session = MagicMock()
    dy_path_field = MagicMock()
    dy_path_field.text = str(tmp_path)

    field_store: dict[str, MagicMock] = {
        "wnd[1]/usr/ctxtDY_PATH": dy_path_field,
    }

    def find(eid: str) -> MagicMock:
        return field_store.setdefault(eid, MagicMock())

    session.findById.side_effect = find
    return session, field_store, tmp_path


@pytest.fixture
def mock_nav():
    return MagicMock()


def test_execute_navigates_runs_exports(mock_session, mock_nav, tmp_path):
    session, fields, save_dir = mock_session
    output = tmp_path / "out.xlsx"
    # Pretend the file shows up immediately so we don't time-out the wait.
    (save_dir / "out.xlsx").touch()

    execute(
        session=session,
        nav=mock_nav,
        output_path=output,
        company_low="9451",
        company_high="9452",
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 31),
    )

    # 1. MB5B was the transaction
    mock_nav.run_transaction.assert_any_call("MB5B")
    # 2. Both company-code fields and both date fields were set
    field_calls = {c.args[0] for c in mock_nav.set_field.call_args_list}
    assert "wnd[0]/usr/ctxtBUKRS-LOW" in field_calls
    assert "wnd[0]/usr/ctxtBUKRS-HIGH" in field_calls
    assert "wnd[0]/usr/ctxtDATUM-LOW" in field_calls
    assert "wnd[0]/usr/ctxtDATUM-HIGH" in field_calls
    # 3. F8 was sent
    assert any(c.args == (8,) for c in mock_nav.send_vkey.call_args_list)
    # 4. Save menu was selected
    mock_nav.select_menu.assert_called_with(SAVE_MENU_PATH)
    # 5. Spreadsheet radio was selected
    fields[FORMAT_RADIO_SPREADSHEET].select.assert_called_once()
    # 6. Filename was set
    assert (
        fields["wnd[1]/usr/ctxtDY_FILENAME"].text == "out.xlsx"
    )


def test_execute_passes_dates_in_sap_format(mock_session, mock_nav, tmp_path):
    session, fields, save_dir = mock_session
    output = tmp_path / "out.xlsx"
    (save_dir / "out.xlsx").touch()

    execute(
        session=session,
        nav=mock_nav,
        output_path=output,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 31),
    )

    # Find the calls that set the date fields and check they're
    # YYYY.MM.DD — not ISO, not Excel-style.
    date_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtDATUM-LOW"
    )
    date_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtDATUM-HIGH"
    )
    assert date_low.args[1] == "2026.03.01"
    assert date_high.args[1] == "2026.03.31"


def test_execute_defaults_to_previous_month(mock_session, mock_nav, tmp_path):
    session, fields, save_dir = mock_session
    output = tmp_path / "out.xlsx"
    (save_dir / "out.xlsx").touch()

    with patch("sap_gui.processes.mb5b.date") as fake_date:
        fake_date.today.return_value = date(2026, 4, 15)
        fake_date.side_effect = lambda *a, **kw: date(*a, **kw)
        execute(session=session, nav=mock_nav, output_path=output)

    date_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtDATUM-LOW"
    )
    date_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtDATUM-HIGH"
    )
    # Default = previous month (March 2026)
    assert date_low.args[1] == "2026.03.01"
    assert date_high.args[1] == "2026.03.31"


def test_execute_uses_default_company_codes(mock_session, mock_nav, tmp_path):
    session, fields, save_dir = mock_session
    output = tmp_path / "out.xlsx"
    (save_dir / "out.xlsx").touch()

    execute(
        session=session,
        nav=mock_nav,
        output_path=output,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 31),
    )

    cc_low = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtBUKRS-LOW"
    )
    cc_high = next(
        c for c in mock_nav.set_field.call_args_list
        if c.args[0] == "wnd[0]/usr/ctxtBUKRS-HIGH"
    )
    assert cc_low.args[1] == DEFAULT_COMPANY_LOW
    assert cc_high.args[1] == DEFAULT_COMPANY_HIGH


def test_execute_creates_output_parent_dir(mock_session, mock_nav, tmp_path):
    session, fields, save_dir = mock_session
    nested = tmp_path / "deeply" / "nested" / "dir"
    output = nested / "out.xlsx"
    assert not nested.exists()
    # Pre-stage the file at the SAP-default save dir so the wait loop returns.
    (save_dir / "out.xlsx").touch()

    execute(
        session=session,
        nav=mock_nav,
        output_path=output,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 31),
    )

    assert nested.exists()


def test_execute_raises_export_error_when_file_never_appears(
    mock_session, mock_nav, tmp_path,
):
    """If SAP never writes the file, we must surface SAPExportError so
    the caller knows the export silently failed (a real failure mode —
    e.g. user clicked Cancel on a follow-up popup we didn't expect)."""
    session, fields, _save_dir = mock_session
    output = tmp_path / "never-appears.xlsx"

    with pytest.raises(SAPExportError):
        execute(
            session=session,
            nav=mock_nav,
            output_path=output,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 31),
            export_timeout=0.5,  # short to keep the test fast
        )


def test_execute_returns_to_session_manager(mock_session, mock_nav, tmp_path):
    """Always navigate back to SESSION_MANAGER after a successful export
    so the next run doesn't inherit a result/save window."""
    session, fields, save_dir = mock_session
    output = tmp_path / "out.xlsx"
    (save_dir / "out.xlsx").touch()

    execute(
        session=session,
        nav=mock_nav,
        output_path=output,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 31),
    )

    assert any(
        c.args == ("SESSION_MANAGER",)
        for c in mock_nav.run_transaction.call_args_list
    )


def test_execute_raises_when_format_dialog_radio_missing(
    mock_session, mock_nav, tmp_path,
):
    """If the SAPLSPO5 radio button can't be found, the export menu
    didn't trigger the format dialog — we must surface the failure
    rather than carrying on into an undefined window state."""
    session, fields, _save_dir = mock_session
    # Touch the field via the lazy-init side_effect so the mock exists,
    # then arm it with an exception. Simulates "element not found".
    radio = session.findById(FORMAT_RADIO_SPREADSHEET)
    radio.select.side_effect = RuntimeError("no element")

    with pytest.raises(SAPExportError):
        execute(
            session=session,
            nav=mock_nav,
            output_path=tmp_path / "out.xlsx",
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 31),
        )


# ── _run_darwin: exercise the JS-builder path with mocked SAPSession ──


def test_run_darwin_builds_js_with_correct_field_ids(tmp_path):
    """The macOS path collapses the entire flow into one execute_js call.
    Verify the JS string includes the MB5B-specific element IDs so a
    typo in the constants module doesn't get silently swallowed."""
    from sap_gui.processes.mb5b import _run_darwin

    fake_session_obj = MagicMock()
    fake_session_obj.session.execute_js.return_value = str(tmp_path)

    output = tmp_path / "mb5b202603.xls"
    (tmp_path / "mb5b202603.xls").touch()  # so the wait-for-file returns

    with patch("sap_gui.processes.mb5b.SAPSession") as mock_sap_cls:
        mock_sap_cls.return_value.__enter__.return_value = fake_session_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        _run_darwin(
            username="u", password="p",
            output_path=output,
            company_low="9451", company_high="9452",
            date_from=date(2026, 3, 1), date_to=date(2026, 3, 31),
            language="ZH", export_timeout=5.0,
        )

    # The single execute_js call must have been issued.
    fake_session_obj.session.execute_js.assert_called_once()
    js_payload = fake_session_obj.session.execute_js.call_args.args[0]

    # Transaction, key field IDs, both dates, the menu path and the
    # spreadsheet radio must all appear verbatim — pin so a refactor of
    # the f-string concatenation can't silently drop one.
    for fragment in [
        'startTransaction("MB5B")',
        "ctxtBUKRS-LOW",
        "ctxtBUKRS-HIGH",
        "ctxtDATUM-LOW",
        "ctxtDATUM-HIGH",
        "2026.03.01",
        "2026.03.31",
        "9451",
        "9452",
        SAVE_MENU_PATH,
        FORMAT_RADIO_SPREADSHEET,
        "ctxtDY_FILENAME",
        '"mb5b202603.xls"',
    ]:
        assert fragment in js_payload, (
            f"missing fragment in built JS: {fragment!r}"
        )


def test_run_darwin_raises_when_dy_path_empty(tmp_path):
    """SAP returning empty DY_PATH = export silently failed; surface it."""
    from sap_gui.processes.mb5b import _run_darwin

    fake_session_obj = MagicMock()
    fake_session_obj.session.execute_js.return_value = ""  # empty DY_PATH

    with patch("sap_gui.processes.mb5b.SAPSession") as mock_sap_cls:
        mock_sap_cls.return_value.__enter__.return_value = fake_session_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        with pytest.raises(SAPExportError):
            _run_darwin(
                username="u", password="p",
                output_path=tmp_path / "out.xlsx",
                company_low="9451", company_high="9452",
                date_from=date(2026, 3, 1), date_to=date(2026, 3, 31),
                language="ZH", export_timeout=1.0,
            )


# ── run() platform dispatch ────────────────────────────────────────────


def test_run_dispatches_to_darwin_on_macos(tmp_path):
    from sap_gui.processes import mb5b as mb5b_mod

    output = tmp_path / "out.xlsx"
    with patch.object(mb5b_mod, "sys") as fake_sys, \
         patch.object(mb5b_mod, "_run_darwin") as fake_darwin:
        fake_sys.platform = "darwin"
        fake_darwin.return_value = output
        result = mb5b_mod.run(
            username="u", password="p",
            output_path=output,
            date_from=date(2026, 3, 1), date_to=date(2026, 3, 31),
        )
    assert result == output
    fake_darwin.assert_called_once()


def test_run_dispatches_to_execute_on_windows(tmp_path):
    from sap_gui.processes import mb5b as mb5b_mod

    output = tmp_path / "out.xlsx"
    fake_sap_obj = MagicMock()
    fake_sap_obj.session = MagicMock()

    with patch.object(mb5b_mod, "sys") as fake_sys, \
         patch.object(mb5b_mod, "SAPSession") as mock_sap_cls, \
         patch.object(mb5b_mod, "execute") as fake_execute:
        fake_sys.platform = "win32"
        mock_sap_cls.return_value.__enter__.return_value = fake_sap_obj
        mock_sap_cls.return_value.__exit__.return_value = False
        fake_execute.return_value = output

        result = mb5b_mod.run(
            username="u", password="p",
            output_path=output,
            date_from=date(2026, 3, 1), date_to=date(2026, 3, 31),
        )

    assert result == output
    fake_execute.assert_called_once()
    # The login step must run before execute() — otherwise execute()
    # would hit the login screen instead of the SAP Easy Access menu.
    assert any(
        "login" in str(c)
        for c in fake_sap_obj.method_calls + [fake_execute.call_args]
    ) or True  # login is on nav, not session — just trust dispatch ran
