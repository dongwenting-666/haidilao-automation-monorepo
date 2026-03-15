"""SAP GUI automation library — cross-platform (Windows COM + macOS Scripting Console)."""

from sap_gui.errors import (
    SAPConnectionError,
    SAPExportError,
    SAPGuiError,
    SAPNavigationError,
    SAPStatusBarError,
)
from sap_gui.export import SAPExporter
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession, SAPSessionManager

__all__ = [
    "SAPConnectionError",
    "SAPExportError",
    "SAPExporter",
    "SAPGuiError",
    "SAPNavigationError",
    "SAPNavigator",
    "SAPSession",
    "SAPSessionManager",
    "SAPStatusBarError",
]
