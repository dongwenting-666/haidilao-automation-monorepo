"""VPN error hierarchy."""


class VPNError(Exception):
    """Base error for VPN operations."""


class VPNAppNotFoundError(VPNError):
    """SealSuite application could not be found or launched."""


class VPNConnectionError(VPNError):
    """Failed to connect or reconnect VPN."""
