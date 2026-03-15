"""Platform dispatcher — imports the correct SAP GUI backend.

On Windows, uses COM/ActiveX via pywin32 (``_win32.py``).
On macOS, uses the SAP GUI for Java Scripting Console (``_darwin.py``).
"""

import sys

from sap_gui.errors import SAPGuiError

if sys.platform == "win32":
    from sap_gui._win32 import SAPSession, SAPSessionManager
elif sys.platform == "darwin":
    from sap_gui._darwin import SAPSession, SAPSessionManager
else:

    class SAPSession:  # type: ignore[no-redef]
        """Stub — SAP GUI automation is only supported on Windows and macOS."""

        def __init__(self, *args, **kwargs):
            raise SAPGuiError(
                f"SAP GUI automation is not supported on {sys.platform}"
            )

    class SAPSessionManager:  # type: ignore[no-redef]
        """Stub — SAP GUI automation is only supported on Windows and macOS."""

        def __init__(self, *args, **kwargs):
            raise SAPGuiError(
                f"SAP GUI automation is not supported on {sys.platform}"
            )
