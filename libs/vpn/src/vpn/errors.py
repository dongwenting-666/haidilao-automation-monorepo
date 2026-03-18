"""VPN error hierarchy and shared constants."""

MAX_POLL_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 3


class VPNError(Exception):
    """Base error for VPN operations."""


class VPNAppNotFoundError(VPNError):
    """SealSuite application could not be found or launched."""


class VPNConnectionError(VPNError):
    """Failed to connect or reconnect VPN."""
