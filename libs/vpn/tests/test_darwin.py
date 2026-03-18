"""Unit tests for vpn._darwin — status parsing and click logic.

These tests run without a live CorpLink instance by mocking filesystem and
subprocess calls.  E2E / integration tests are in test_e2e.py.
"""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Real CorpLink log line formats
_LOG_CONNECTED = (
    "CorpLink 2026/03/18 05:00:00.000000 report.go:92: "
    "reportVpnStatus start map[ip:2.1.31.187 mode:Split "
    "public_key:abc= smac:14:98:77:2f:4d:f5 type:100]\n"
)
_LOG_DISCONNECTED = (
    "CorpLink 2026/03/18 08:00:00.000000 vpn.go:579: VPN Disconnected\n"
)


# ---------------------------------------------------------------------------
# _parse_log_status
# ---------------------------------------------------------------------------

class TestParseLogStatus:
    def test_connected_returns_true_and_timestamp(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text(_LOG_CONNECTED)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _parse_log_status
            connected, ts = _parse_log_status()

        assert connected is True
        assert isinstance(ts, datetime)
        assert ts == datetime(2026, 3, 18, 5, 0, 0)

    def test_disconnected_returns_false(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text(_LOG_CONNECTED + _LOG_DISCONNECTED)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _parse_log_status
            connected, ts = _parse_log_status()

        assert connected is False
        assert ts is None

    def test_missing_log_returns_false(self, tmp_path):
        with patch("vpn._darwin.CORPLINK_LOG", tmp_path / "nonexistent.log"):
            from vpn._darwin import _parse_log_status
            connected, ts = _parse_log_status()

        assert connected is False
        assert ts is None

    def test_empty_log_returns_false(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text("")

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _parse_log_status
            connected, ts = _parse_log_status()

        assert connected is False


# ---------------------------------------------------------------------------
# _is_connected / _get_connected_hours
# ---------------------------------------------------------------------------

class TestConnectionHelpers:
    def test_is_connected_true(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text(_LOG_CONNECTED)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _is_connected
            assert _is_connected() is True

    def test_is_connected_false(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text(_LOG_DISCONNECTED)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _is_connected
            assert _is_connected() is False

    def test_get_connected_hours_returns_float(self, tmp_path):
        two_hours_ago = datetime.now() - timedelta(hours=2)
        ts_str = two_hours_ago.strftime("%Y/%m/%d %H:%M:%S")
        line = (
            f"CorpLink {ts_str}.000000 report.go:92: "
            "reportVpnStatus start map[ip:1.2.3.4 mode:Split "
            "public_key=x smac:aa type:100]\n"
        )
        log_file = tmp_path / "corplink.log"
        log_file.write_text(line)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _get_connected_hours
            hours = _get_connected_hours()

        assert hours is not None
        assert 1.9 < hours < 2.1

    def test_get_connected_hours_when_disconnected(self, tmp_path):
        log_file = tmp_path / "corplink.log"
        log_file.write_text(_LOG_DISCONNECTED)

        with patch("vpn._darwin.CORPLINK_LOG", log_file):
            from vpn._darwin import _get_connected_hours
            assert _get_connected_hours() is None


# ---------------------------------------------------------------------------
# _cliclick
# ---------------------------------------------------------------------------

class TestCliclick:
    def test_success(self):
        from vpn._darwin import _cliclick
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _cliclick("c:100,200")
            assert mock_run.call_args[0][0] == ["cliclick", "c:100,200"]

    def test_not_installed_raises(self):
        from vpn._darwin import _cliclick
        from vpn.errors import VPNConnectionError
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(VPNConnectionError, match="cliclick not found"):
                _cliclick("c:100,200")

    def test_nonzero_exit_raises(self):
        from vpn._darwin import _cliclick
        from vpn.errors import VPNConnectionError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="bad coords")
            with pytest.raises(VPNConnectionError, match="cliclick failed"):
                _cliclick("c:bad")

    def test_timeout_raises(self):
        from vpn._darwin import _cliclick
        from vpn.errors import VPNConnectionError
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cliclick", 10)):
            with pytest.raises(VPNConnectionError, match="timed out"):
                _cliclick("c:100,200")


# ---------------------------------------------------------------------------
# _connect_vpn
# ---------------------------------------------------------------------------

class TestConnectVpn:
    def _make_as_result(self, returncode=0, stdout="100,100,888,560", stderr=""):
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def test_happy_path_clicks_overview_toggle(self):
        from vpn._darwin import _OVERVIEW_TOGGLE_DX, _OVERVIEW_TOGGLE_DY, _connect_vpn
        clicks = []

        def fake_run(cmd, **kwargs):
            if cmd[0] == "osascript":
                script = " ".join(cmd)
                if "position of window" in script:
                    return self._make_as_result()
            if cmd[0] == "cliclick":
                clicks.append(cmd[1])
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), patch("time.sleep"):
            _connect_vpn()

        # Should have: move to toggle + click toggle
        click_coords = [c for c in clicks if c.startswith("c:") or c.startswith("m:")]
        expected_toggle = f"c:{100 + _OVERVIEW_TOGGLE_DX},{100 + _OVERVIEW_TOGGLE_DY}"
        assert any(expected_toggle in c for c in click_coords), \
            f"Should click Overview VPN toggle at {expected_toggle}"

    def test_no_window_raises_app_not_found(self):
        from vpn._darwin import _connect_vpn
        from vpn.errors import VPNAppNotFoundError

        def fake_run(cmd, **kwargs):
            if cmd[0] == "osascript":
                return self._make_as_result(stdout="NO_WINDOW")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), patch("time.sleep"):
            with pytest.raises(VPNAppNotFoundError):
                _connect_vpn()

    def test_applescript_error_raises(self):
        from vpn._darwin import _connect_vpn
        from vpn.errors import VPNAppNotFoundError

        def fake_run(cmd, **kwargs):
            if cmd[0] == "osascript":
                return self._make_as_result(returncode=1, stderr="scripting error")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), patch("time.sleep"):
            with pytest.raises(VPNAppNotFoundError):
                _connect_vpn()


# ---------------------------------------------------------------------------
# _launch_fresh
# ---------------------------------------------------------------------------

class TestLaunchFresh:
    def test_quits_then_launches(self):
        from vpn._darwin import _launch_fresh

        with patch("vpn._darwin._quit_app") as mock_quit, \
             patch("vpn._darwin._find_app", return_value=Path("/Applications/CorpLink.app")), \
             patch("subprocess.Popen") as mock_popen, \
             patch("vpn._darwin._is_running", side_effect=[False, False, True]), \
             patch("time.sleep"):
            _launch_fresh()

        mock_quit.assert_called_once()
        mock_popen.assert_called_once()

    def test_raises_if_process_never_appears(self):
        from vpn._darwin import _launch_fresh
        from vpn.errors import VPNAppNotFoundError

        with patch("vpn._darwin._quit_app"), \
             patch("vpn._darwin._find_app", return_value=Path("/Applications/CorpLink.app")), \
             patch("subprocess.Popen"), \
             patch("vpn._darwin._is_running", return_value=False), \
             patch("time.sleep"):
            with pytest.raises(VPNAppNotFoundError, match="did not appear"):
                _launch_fresh()


# ---------------------------------------------------------------------------
# ensure_vpn
# ---------------------------------------------------------------------------

class TestEnsureVpn:
    def test_already_connected_healthy_does_nothing(self):
        from vpn.connect import ensure_vpn

        with patch("vpn._darwin._is_connected", return_value=True), \
             patch("vpn._darwin._get_connected_hours", return_value=1.0), \
             patch("vpn._darwin._launch_fresh") as mock_launch:
            ensure_vpn(max_connected_hours=6.0)

        mock_launch.assert_not_called()

    def test_disconnected_launches_and_connects(self):
        from vpn.connect import ensure_vpn

        # After launch+click: VPN comes up on 3rd poll
        connected_states = iter([False, False, False, True])

        with patch("vpn._darwin._is_connected", side_effect=connected_states), \
             patch("vpn._darwin._launch_fresh") as mock_launch, \
             patch("vpn._darwin._connect_vpn") as mock_connect, \
             patch("subprocess.run"), \
             patch("time.sleep"):
            ensure_vpn()

        mock_launch.assert_called_once()
        mock_connect.assert_called_once()

    def test_session_too_old_reconnects(self):
        from vpn.connect import ensure_vpn

        # Connected for 7h (stale) → launches fresh
        connected_states = iter([True, True, True, True])

        with patch("vpn._darwin._is_connected", side_effect=connected_states), \
             patch("vpn._darwin._get_connected_hours", return_value=7.0), \
             patch("vpn._darwin._launch_fresh") as mock_launch, \
             patch("vpn._darwin._connect_vpn") as mock_connect, \
             patch("vpn._darwin._quit_app"), \
             patch("time.sleep"):
            ensure_vpn(max_connected_hours=6.0)

        mock_launch.assert_called_once()
        mock_connect.assert_called_once()

    def test_vpn_never_connects_raises(self):
        from vpn.connect import ensure_vpn
        from vpn.errors import VPNConnectionError

        with patch("vpn._darwin._is_connected", return_value=False), \
             patch("vpn._darwin._launch_fresh"), \
             patch("vpn._darwin._connect_vpn"), \
             patch("vpn._darwin._quit_app"), \
             patch("time.sleep"):
            with pytest.raises(VPNConnectionError, match="did not connect"):
                ensure_vpn()
