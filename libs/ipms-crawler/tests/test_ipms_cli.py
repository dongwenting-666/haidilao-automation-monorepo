"""CLI dispatch tests — verifies argparse routing without a real browser.

We don't test the click handlers (those are exercised by the actual run);
we test that the right entry points are reached with the right args, and
that subcommand-specific flags propagate correctly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ipms_crawler.__main__ import main
from ipms_crawler.scraper import DEFAULT_TABS


def _run(monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", argv)
    main()


def test_login_subcommand_invokes_interactive_login(monkeypatch):
    with patch(
        "ipms_crawler.__main__.IPMSSession.interactive_login"
    ) as mock_login:
        _run(monkeypatch, ["ipms_crawler", "login", "--timeout", "60"])
    mock_login.assert_called_once()
    assert mock_login.call_args.kwargs["timeout_s"] == 60


def test_login_passes_har_path(monkeypatch, tmp_path):
    har = tmp_path / "trace.har"
    with patch(
        "ipms_crawler.__main__.IPMSSession.interactive_login"
    ) as mock_login:
        _run(
            monkeypatch,
            ["ipms_crawler", "login", "--har", str(har), "--browse"],
        )
    kwargs = mock_login.call_args.kwargs
    assert kwargs["har_path"] == har
    assert kwargs["browse_after_login"] is True


def test_download_bom_uses_default_tabs_when_unspecified(
    monkeypatch, tmp_path
):
    with patch("ipms_crawler.__main__.download_bom") as mock_dl:
        mock_dl.return_value = []
        _run(
            monkeypatch,
            [
                "ipms_crawler",
                "download-bom",
                "--output-dir",
                str(tmp_path),
                "--no-headless",
            ],
        )
    kwargs = mock_dl.call_args.kwargs
    assert kwargs["tabs"] == DEFAULT_TABS
    assert kwargs["region"] == "加拿大"
    assert kwargs["headless"] is False
    assert kwargs["output_dir"] == tmp_path


def test_download_bom_custom_tabs(monkeypatch, tmp_path):
    # Single-tab override — when ops needs to re-run only 锅底.
    with patch("ipms_crawler.__main__.download_bom") as mock_dl:
        mock_dl.return_value = []
        _run(
            monkeypatch,
            [
                "ipms_crawler",
                "download-bom",
                "--tabs",
                "锅底",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert mock_dl.call_args.kwargs["tabs"] == ("锅底",)


def test_download_bom_custom_region(monkeypatch, tmp_path):
    with patch("ipms_crawler.__main__.download_bom") as mock_dl:
        mock_dl.return_value = []
        _run(
            monkeypatch,
            [
                "ipms_crawler",
                "download-bom",
                "--region",
                "美国",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert mock_dl.call_args.kwargs["region"] == "美国"


def test_skip_vpn_propagates_to_session(monkeypatch):
    """`--skip-vpn` is a top-level flag that must reach IPMSSession."""
    with patch("ipms_crawler.__main__.IPMSSession") as mock_session:
        # Make `with IPMSSession(...) as session:` work.
        ctx = mock_session.return_value.__enter__.return_value
        ctx.page.url = "https://ipms-global.superhi-tech.com/myMessage"
        _run(monkeypatch, ["ipms_crawler", "--skip-vpn", "verify"])
    assert mock_session.call_args.kwargs["skip_vpn"] is True


def test_skip_vpn_propagates_to_download_bom(monkeypatch, tmp_path):
    with patch("ipms_crawler.__main__.download_bom") as mock_dl:
        mock_dl.return_value = []
        _run(
            monkeypatch,
            [
                "ipms_crawler",
                "--skip-vpn",
                "download-bom",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert mock_dl.call_args.kwargs["skip_vpn"] is True


def test_verify_exits_nonzero_on_session_error(monkeypatch, capsys):
    """A failed session in `verify` must exit 1 — the cron caller relies
    on the exit code to alert."""
    from ipms_crawler.errors import IPMSLoginExpiredError

    with patch("ipms_crawler.__main__.IPMSSession") as mock_session:
        mock_session.return_value.__enter__.side_effect = (
            IPMSLoginExpiredError("expired")
        )
        with pytest.raises(SystemExit) as exc_info:
            _run(monkeypatch, ["ipms_crawler", "verify"])
    assert exc_info.value.code == 1


def test_unknown_subcommand_exits(monkeypatch):
    # argparse prints usage and exits — verify SystemExit propagates.
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["ipms_crawler", "nonsense-command"])


def test_no_subcommand_exits(monkeypatch):
    # `subparsers(required=True)` rejects empty subcommand. If someone
    # flips required=False the CLI silently no-ops — guard against that.
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["ipms_crawler"])
