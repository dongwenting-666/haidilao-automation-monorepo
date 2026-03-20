"""E2E / integration tests for vpn._darwin — require a live macOS + CorpLink.

Run manually when the automation Mac is available:

    uv run --project libs/vpn pytest libs/vpn/tests/test_e2e.py -v -s

These tests are skipped automatically on non-Darwin platforms and when
CorpLink is not installed.
"""

import sys
from pathlib import Path

import pytest

CORPLINK_APP = Path("/Applications/CorpLink.app")
CORPLINK_LOG = Path("/usr/local/corplink/logs/corplink.log")

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS only"
)
requires_corplink = pytest.mark.skipif(
    not CORPLINK_APP.exists() or not CORPLINK_LOG.exists(),
    reason="CorpLink not installed",
)


@darwin_only
@requires_corplink
class TestE2E:
    """Live tests against a real CorpLink installation.

    WARNING: these tests quit and relaunch CorpLink and will briefly
    disconnect the VPN.  Do not run during active automation jobs.
    """

    def test_status_detection(self):
        """_is_connected() and _is_running() return bools without error."""
        from vpn._darwin import _is_connected, _is_running
        assert isinstance(_is_running(), bool)
        assert isinstance(_is_connected(), bool)

    def test_connected_hours_type(self):
        """_get_connected_hours() returns float or None, never raises."""
        from vpn._darwin import _get_connected_hours, _is_connected
        hours = _get_connected_hours()
        if _is_connected():
            assert isinstance(hours, float)
            assert hours >= 0
        else:
            assert hours is None

    def test_ensure_vpn_connects(self):
        """ensure_vpn() leaves VPN connected."""
        from vpn import ensure_vpn
        from vpn._darwin import _is_connected
        ensure_vpn()
        assert _is_connected(), "VPN should be connected after ensure_vpn()"

    def test_ensure_vpn_idempotent(self):
        """Calling ensure_vpn() twice is safe — second call is a no-op."""
        from vpn import ensure_vpn
        from vpn._darwin import _is_connected
        ensure_vpn()
        assert _is_connected()
        ensure_vpn()  # should return immediately (session healthy)
        assert _is_connected()

    def test_session_cycle_when_stale(self):
        """ensure_vpn() reconnects when session is older than max_connected_hours.

        We mock _get_connected_hours to simulate a stale session rather than
        actually waiting 6+ hours.  The function should quit CorpLink, relaunch,
        and reconnect.
        """
        from unittest.mock import patch
        from vpn import ensure_vpn
        from vpn._darwin import _is_connected

        # Must already be connected for the stale-session path to trigger.
        if not _is_connected():
            ensure_vpn()  # bring VPN up first

        assert _is_connected(), "Need VPN connected to test stale-session cycle"

        # Fake a 7-hour session so ensure_vpn thinks it needs a cycle.
        with patch("vpn._darwin._get_connected_hours", return_value=7.0):
            ensure_vpn(max_connected_hours=6.0)

        assert _is_connected(), "VPN should be reconnected after stale-session cycle"
