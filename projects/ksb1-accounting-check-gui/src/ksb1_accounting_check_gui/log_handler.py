"""Thread-safe logging handler that writes to a tkinter Text widget."""

from __future__ import annotations

import logging
import queue
import tkinter as tk


class QueueLogHandler(logging.Handler):
    """Logging handler that puts log records into a queue.

    A periodic tkinter `after()` call drains the queue into a Text widget,
    ensuring thread safety (tkinter is single-threaded).
    """

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[str] = queue.Queue()

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self._queue.put(msg + "\n")

    def install(self, text_widget: tk.Text, poll_ms: int = 100) -> None:
        """Start polling the queue and writing messages to the text widget."""
        self._widget = text_widget
        self._poll_ms = poll_ms
        self._poll()

    def _poll(self) -> None:
        if not self._widget.winfo_exists():
            return
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            self._widget.configure(state=tk.NORMAL)
            self._widget.insert(tk.END, msg)
            self._widget.see(tk.END)
            self._widget.configure(state=tk.DISABLED)
        self._widget.after(self._poll_ms, self._poll)
