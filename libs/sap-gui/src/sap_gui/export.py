"""Export SAP report data to local files via SAP GUI."""

from __future__ import annotations

import time
from pathlib import Path

from sap_gui.errors import SAPExportError
from sap_gui.navigation import SAPNavigator


class SAPExporter:
    """Exports SAP report data to a local file."""

    _DEFAULT_GRID_ID = "wnd[0]/usr/cntlGRID1/shellcont/shell"
    _DEFAULT_MENU_PATH = "wnd[0]/mbar/menu[0]/menu[3]/menu[1]"

    def __init__(self, session, navigator: SAPNavigator) -> None:
        self._session = session
        self._navigator = navigator

    def _fill_save_dialog(
        self, output_dir: str, filename: str, dialog_window: int = 1
    ) -> None:
        """Fill DY_PATH/DY_FILENAME in the save dialog and press save."""
        wnd = f"wnd[{dialog_window}]"
        try:
            self._session.findById(f"{wnd}/usr/ctxtDY_PATH").text = output_dir
            self._session.findById(f"{wnd}/usr/ctxtDY_FILENAME").text = filename
            self._session.findById(f"{wnd}/tbar[0]/btn[0]").press()
        except Exception as exc:
            raise SAPExportError(
                "Failed to fill save dialog. The export dialog may not have appeared."
            ) from exc
        # Handle potential "replace existing file?" popup — only dismiss
        # if a popup actually appeared at a higher window index
        self._navigator.dismiss_popup(window=dialog_window + 1, vkey=0)

    def _wait_for_file(self, output_path: Path, timeout: float) -> None:
        """Wait for a file to appear on disk."""
        start = time.monotonic()
        while not output_path.exists():
            if time.monotonic() - start > timeout:
                raise SAPExportError(
                    f"Export timed out — file not created at {output_path} "
                    f"within {timeout}s"
                )
            time.sleep(0.5)

    def export_alv_to_file(
        self,
        output_path: Path,
        grid_id: str = _DEFAULT_GRID_ID,
        timeout: float = 10.0,
    ) -> Path:
        """Export an ALV grid via its context menu -> Spreadsheet.

        Use this for transactions that display results in an ALV grid control.
        """
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            grid = self._session.findById(grid_id)
            grid.pressToolbarContextButton("&MB_EXPORT")
            grid.selectContextMenuItem("&XXL")
        except Exception as exc:
            raise SAPExportError(
                "Failed to trigger ALV export. "
                "Ensure an ALV grid is displayed on screen."
            ) from exc

        self._fill_save_dialog(str(output_path.parent), output_path.name)
        self._wait_for_file(output_path, timeout)
        return output_path

    def export_list_to_file(
        self,
        output_path: Path,
        menu_path: str = _DEFAULT_MENU_PATH,
        dialog_window: int = 1,
        timeout: float = 10.0,
    ) -> Path:
        """Export a classic list/report via menu bar -> Local File.

        Use this for transactions like KSB1 that show results as a classic
        list rather than an ALV grid. The default menu path corresponds to
        List -> Export -> Spreadsheet.

        Args:
            output_path: Destination file path (parent directory is created if needed).
            menu_path: SAP element ID of the export menu item.
            dialog_window: Window index where the save dialog appears.
            timeout: Seconds to wait for the file to appear.
        """
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._navigator.select_menu(menu_path)

        self._fill_save_dialog(
            str(output_path.parent), output_path.name, dialog_window
        )
        self._wait_for_file(output_path, timeout)
        return output_path
