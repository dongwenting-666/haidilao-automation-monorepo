"""SealSuite VPN connection middleware — platform dispatcher.

Delegates to the platform-specific implementation:
- Windows: pywinauto + winreg (``_windows.py``)
- macOS: log parsing + AppleScript (``_darwin.py``)
"""

import sys

from vpn.errors import VPNError

if sys.platform == "win32":
    from vpn._windows import ensure_vpn
elif sys.platform == "darwin":
    from vpn._darwin import ensure_vpn
else:
    def ensure_vpn(*, max_connected_hours: float = 6.0) -> None:
        """Raise on unsupported platforms."""
        _ = max_connected_hours  # unused — signature kept for API compat
        raise VPNError(f"VPN middleware is not supported on {sys.platform!r}")

__all__ = ["ensure_vpn"]
