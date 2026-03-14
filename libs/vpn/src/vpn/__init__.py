"""SealSuite VPN middleware — call ensure_vpn() before any automation.

Usage:
    from vpn import ensure_vpn

    ensure_vpn()  # blocks until VPN is ready, raises on failure
    # ... run your automation ...
"""

from vpn.connect import ensure_vpn
from vpn.errors import VPNAppNotFoundError, VPNConnectionError, VPNError

__all__ = [
    "ensure_vpn",
    "VPNError",
    "VPNAppNotFoundError",
    "VPNConnectionError",
]
