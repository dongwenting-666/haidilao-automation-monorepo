"""Tests for the standalone zfi0156_app.py CLI — argparse routing only."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_app():
    app_path = Path(__file__).resolve().parents[1] / "zfi0156_app.py"
    spec = importlib.util.spec_from_file_location("zfi0156_app", app_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def app():
    return _load_app()


def _run_main(app, monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("SAP_USERNAME", "user")
    monkeypatch.setenv("SAP_PASSWORD", "pw")
    monkeypatch.setenv("SAP_LANGUAGE", "ZH")
    app.main()


# ── parse_date ─────────────────────────────────────────────────────────


def test_parse_date_accepts_dotted_format(app):
    assert app.parse_date("2026.02.01") == date(2026, 2, 1)


def test_parse_date_accepts_iso(app):
    assert app.parse_date("2026-02-01") == date(2026, 2, 1)


def test_parse_date_rejects_garbage(app):
    with pytest.raises(ValueError):
        app.parse_date("not-a-date")


# ── main() argument routing ────────────────────────────────────────────


def test_main_uses_previous_month_when_no_dates(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.zfi0156.run") as fake_run, \
         patch("vpn.ensure_vpn") as fake_vpn:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            ["zfi0156", "--no-vpn", "--output", str(out)],
        )
    kwargs = fake_run.call_args.kwargs
    assert isinstance(kwargs["date_from"], date)
    assert isinstance(kwargs["date_to"], date)
    assert kwargs["date_from"].day == 1
    assert kwargs["date_from"].month == kwargs["date_to"].month
    # Default plants = Canada range
    assert kwargs["plant_low"] == "CA01"
    assert kwargs["plant_high"] == "CA09"
    fake_vpn.assert_not_called()


def test_main_passes_explicit_dates(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.zfi0156.run") as fake_run:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "zfi0156", "--no-vpn",
                "--from", "2026.02.01",
                "--to", "2026.02.28",
                "--output", str(out),
            ],
        )
    kwargs = fake_run.call_args.kwargs
    assert kwargs["date_from"] == date(2026, 2, 1)
    assert kwargs["date_to"] == date(2026, 2, 28)


def test_main_passes_custom_plants(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.zfi0156.run") as fake_run:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "zfi0156", "--no-vpn",
                "--plant-low", "CA05",
                "--plant-high", "CA05",
                "--output", str(out),
            ],
        )
    kwargs = fake_run.call_args.kwargs
    assert kwargs["plant_low"] == "CA05"
    assert kwargs["plant_high"] == "CA05"


def test_main_default_output_uses_default_filename(app, monkeypatch):
    """No --output: falls back to output/sap/zfi0156-{YYYYMM}.xlsx."""
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.zfi0156.run") as fake_run:
        fake_run.return_value = Path("/tmp/x.xlsx")
        _run_main(
            app, monkeypatch,
            ["zfi0156", "--no-vpn", "--from", "2026.02.01", "--to", "2026.02.28"],
        )
    kwargs = fake_run.call_args.kwargs
    out: Path = kwargs["output_path"]
    assert out.parent.parts[-2:] == ("output", "sap")
    assert out.name == "zfi0156-202602.xlsx"


def test_main_calls_ensure_vpn_by_default(app, monkeypatch, tmp_path):
    out = tmp_path / "x.xlsx"
    with patch.object(app, "load_dotenv"), \
         patch("sap_gui.processes.zfi0156.run") as fake_run, \
         patch("vpn.ensure_vpn") as fake_vpn:
        fake_run.return_value = out
        _run_main(
            app, monkeypatch,
            [
                "zfi0156",
                "--from", "2026.02.01",
                "--to", "2026.02.28",
                "--output", str(out),
            ],
        )
    fake_vpn.assert_called_once()


def test_main_exits_when_credentials_missing(app, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["zfi0156", "--no-vpn"])
    monkeypatch.delenv("SAP_USERNAME", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    with patch.object(app, "load_dotenv"):
        with pytest.raises(SystemExit) as exc:
            app.main()
    assert exc.value.code == 1
