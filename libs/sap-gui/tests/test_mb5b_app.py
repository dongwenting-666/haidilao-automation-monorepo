"""Tests for the standalone mb5b_app.py CLI — argparse routing only.

We don't run the actual SAP flow; we verify that flag parsing and
defaults match expectations, since the CLI is the operator-facing
contract for the PyInstaller binary.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_app():
    """Import mb5b_app.py by file path (it lives next to libs/sap-gui/)."""
    app_path = Path(__file__).resolve().parents[1] / "mb5b_app.py"
    spec = importlib.util.spec_from_file_location("mb5b_app", app_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def app():
    return _load_app()


# ── parse_date ─────────────────────────────────────────────────────────


def test_parse_date_accepts_dotted_format(app):
    # SAP-style YYYY.MM.DD, matches what set_field expects.
    assert app.parse_date("2026.03.15") == date(2026, 3, 15)


def test_parse_date_accepts_iso(app):
    # Be lenient with operator input — both forms map to the same date.
    assert app.parse_date("2026-03-15") == date(2026, 3, 15)


def test_parse_date_rejects_garbage(app):
    with pytest.raises(ValueError):
        app.parse_date("not-a-date")


# ── main() argument routing ────────────────────────────────────────────


def _run_main(app, monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("SAP_USERNAME", "user")
    monkeypatch.setenv("SAP_PASSWORD", "pw")
    monkeypatch.setenv("SAP_LANGUAGE", "ZH")
    app.main()


def test_main_uses_previous_month_when_no_dates(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.mb5b.run") as fake_run, \
         patch("vpn.ensure_vpn") as fake_vpn:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            ["mb5b", "--no-vpn", "--output", str(out)],
        )
    assert fake_run.called
    kwargs = fake_run.call_args.kwargs
    # Defaults: previous month, not None
    assert isinstance(kwargs["date_from"], date)
    assert isinstance(kwargs["date_to"], date)
    assert kwargs["date_from"].day == 1
    assert kwargs["date_from"].month == kwargs["date_to"].month
    # Default companies
    assert kwargs["company_low"] == "9451"
    assert kwargs["company_high"] == "9452"
    # No VPN call when --no-vpn
    fake_vpn.assert_not_called()


def test_main_passes_explicit_dates(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.mb5b.run") as fake_run:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "mb5b", "--no-vpn",
                "--from", "2026.02.01",
                "--to", "2026.02.28",
                "--output", str(out),
            ],
        )
    kwargs = fake_run.call_args.kwargs
    assert kwargs["date_from"] == date(2026, 2, 1)
    assert kwargs["date_to"] == date(2026, 2, 28)


def test_main_passes_custom_company_codes(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.mb5b.run") as fake_run:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "mb5b", "--no-vpn",
                "--company-low", "9999",
                "--company-high", "9999",
                "--output", str(out),
            ],
        )
    kwargs = fake_run.call_args.kwargs
    assert kwargs["company_low"] == "9999"
    assert kwargs["company_high"] == "9999"


def test_main_default_output_uses_default_filename_in_output_sap(
    app, monkeypatch,
):
    """No --output: the path falls back to output/sap/mb5b{YYYYMM}.xls."""
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.mb5b.run") as fake_run:
        fake_run.return_value = Path("/tmp/x.xls")
        _run_main(
            app, monkeypatch,
            ["mb5b", "--no-vpn", "--from", "2026.03.01", "--to", "2026.03.31"],
        )
    kwargs = fake_run.call_args.kwargs
    out: Path = kwargs["output_path"]
    assert out.parent.parts[-2:] == ("output", "sap")
    assert out.name == "mb5b202603.xls"


def test_main_calls_ensure_vpn_by_default(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.mb5b.run") as fake_run, \
         patch("vpn.ensure_vpn") as fake_vpn:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "mb5b",
                "--from", "2026.03.01",
                "--to", "2026.03.31",
                "--output", str(out),
            ],
        )
    fake_vpn.assert_called_once()


def test_main_exits_when_credentials_missing(app, monkeypatch, capsys):
    """Without SAP_USERNAME/PASSWORD, the CLI must hard-fail. The cron
    caller relies on a non-zero exit to alert ops."""
    monkeypatch.setattr(sys, "argv", ["mb5b", "--no-vpn"])
    monkeypatch.delenv("SAP_USERNAME", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    with patch.object(app, "load_dotenv"):
        with pytest.raises(SystemExit) as exc:
            app.main()
    assert exc.value.code == 1
