"""KSB1 Accounting Check — tkinter GUI application."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ksb1_accounting_check_gui.log_handler import QueueLogHandler
from ksb1_accounting_check_gui.paths import exe_dir, resource_path
from ksb1_accounting_check_gui.worker import run_download_and_generate, run_generate_only

WINDOW_TITLE = "KSB1 会计检查"
WINDOW_SIZE = "700x720"


def _reveal_in_file_manager(path: Path) -> None:
    """Open the containing folder and reveal the generated report."""
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", "-R", str(path)])
        return
    if system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path.parent)])


def _prev_month_year() -> tuple[int, int]:
    today = date.today()
    if today.month == 1:
        return 12, today.year - 1
    return today.month - 1, today.year


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_SIZE)
        root.resizable(True, True)

        self._setup_logging()
        self._build_ui()
        self._load_defaults()

    def _setup_logging(self) -> None:
        self.log_handler = QueueLogHandler()
        self.log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[self.log_handler])

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- Credentials ---
        cred_frame = ttk.LabelFrame(self.root, text="SAP 登录", padding=8)
        cred_frame.pack(fill=tk.X, **pad)

        ttk.Label(cred_frame, text="用户名:").grid(row=0, column=0, sticky=tk.W)
        self.username_var = tk.StringVar()
        ttk.Entry(cred_frame, textvariable=self.username_var, width=25).grid(row=0, column=1, **pad)

        ttk.Label(cred_frame, text="密码:").grid(row=0, column=2, sticky=tk.W)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(cred_frame, textvariable=self.password_var, width=25, show="*")
        self.password_entry.grid(row=0, column=3, **pad)

        self.show_pw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cred_frame, text="显示", variable=self.show_pw_var,
            command=self._toggle_password,
        ).grid(row=0, column=4)

        # --- Settings ---
        settings_frame = ttk.LabelFrame(self.root, text="设置", padding=8)
        settings_frame.pack(fill=tk.X, **pad)

        ttk.Label(settings_frame, text="月份:").grid(row=0, column=0, sticky=tk.W)
        self.month_var = tk.IntVar()
        ttk.Spinbox(settings_frame, from_=1, to=12, textvariable=self.month_var, width=5).grid(row=0, column=1, **pad)

        ttk.Label(settings_frame, text="年份:").grid(row=0, column=2, sticky=tk.W)
        self.year_var = tk.IntVar()
        ttk.Spinbox(settings_frame, from_=2020, to=2030, textvariable=self.year_var, width=7).grid(row=0, column=3, **pad)

        ttk.Label(settings_frame, text="语言:").grid(row=0, column=4, sticky=tk.W)
        self.language_var = tk.StringVar(value="ZH")
        ttk.Combobox(
            settings_frame, textvariable=self.language_var,
            values=["ZH", "EN"], width=5, state="readonly",
        ).grid(row=0, column=5, **pad)

        # --- Output directory ---
        dir_frame = ttk.LabelFrame(self.root, text="输出目录", padding=8)
        dir_frame.pack(fill=tk.X, **pad)

        self.output_dir_var = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.output_dir_var, width=60).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(dir_frame, text="浏览...", command=self._browse_output_dir).pack(side=tk.RIGHT, padx=(8, 0))

        # --- LLM option ---
        llm_frame = ttk.LabelFrame(self.root, text="LLM 增强（可选）", padding=8)
        llm_frame.pack(fill=tk.X, **pad)

        self.model_var = tk.StringVar(value="")
        ttk.Label(llm_frame, text="模型:").pack(side=tk.LEFT)
        ttk.Combobox(
            llm_frame, textvariable=self.model_var,
            values=["", "qwen3:8b", "qwen3:14b", "qwen3:32b"], width=20,
        ).pack(side=tk.LEFT, padx=8)
        ttk.Label(llm_frame, text="留空 = 仅规则分析（推荐）", foreground="gray").pack(side=tk.LEFT)

        # --- Cost centers ---
        cc_frame = ttk.LabelFrame(self.root, text="成本中心（每行一个）", padding=8)
        cc_frame.pack(fill=tk.X, **pad)

        self.cost_center_text = tk.Text(cc_frame, height=5, width=60)
        cc_scroll = ttk.Scrollbar(cc_frame, orient=tk.VERTICAL, command=self.cost_center_text.yview)
        self.cost_center_text.configure(yscrollcommand=cc_scroll.set)
        cc_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cost_center_text.pack(fill=tk.X, expand=True)

        # --- Action buttons ---
        btn_frame = ttk.Frame(self.root, padding=8)
        btn_frame.pack(fill=tk.X)

        self.btn_download = ttk.Button(
            btn_frame, text="下载 SAP 数据 + 生成报告",
            command=self._on_download_and_generate,
        )
        self.btn_download.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self.btn_generate = ttk.Button(
            btn_frame, text="仅生成报告（跳过下载）",
            command=self._on_generate_only,
        )
        self.btn_generate.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # --- Log output ---
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED, height=12)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Start log polling
        self.log_handler.install(self.log_text)

    def _load_defaults(self) -> None:
        # Load .env if present next to EXE
        env_path = exe_dir() / ".env"
        if env_path.exists():
            from dotenv import dotenv_values
            values = dotenv_values(env_path)
            self.username_var.set(values.get("SAP_USERNAME", ""))
            self.password_var.set(values.get("SAP_PASSWORD", ""))

        # Also check environment variables
        if not self.username_var.get():
            self.username_var.set(os.getenv("SAP_USERNAME", ""))
        if not self.password_var.get():
            self.password_var.set(os.getenv("SAP_PASSWORD", ""))

        # Default month/year
        month, year = _prev_month_year()
        self.month_var.set(month)
        self.year_var.set(year)

        # Default output dir
        default_dir = exe_dir() / "output" / "ksb1"
        self.output_dir_var.set(str(default_dir))

        # Load saved cost centers (user's own), falling back to bundled default
        self._cc_save_path = exe_dir() / "user_cost_centers.txt"
        cc_path = self._cc_save_path if self._cc_save_path.exists() else resource_path("cost_centers.txt")
        if cc_path.exists():
            self.cost_center_text.insert("1.0", cc_path.read_text(encoding="utf-8").strip())

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_pw_var.get() else "*")

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if path:
            self.output_dir_var.set(path)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.btn_download.configure(state=state)
        self.btn_generate.configure(state=state)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_done(self, success: bool, message: str) -> None:
        """Called from worker thread when done. Schedules UI update on main thread."""
        self.root.after(0, self._finish, success, message)

    def _finish(self, success: bool, message: str) -> None:
        self._set_running(False)
        if success:
            logging.info("=" * 40)
            logging.info("报告已生成: %s", message)
            # Ask user if they want to open the output folder
            report_path = Path(message)
            if messagebox.askyesno(
                "完成",
                f"报告已生成！\n\n{report_path.name}\n\n是否打开所在文件夹？",
            ):
                _reveal_in_file_manager(report_path)
        else:
            logging.error("=" * 40)
            logging.error("失败: %s", message)
            messagebox.showerror("错误", message)

    def _get_model(self) -> str | None:
        m = self.model_var.get().strip()
        return m if m else None

    def _save_cost_centers(self) -> Path:
        """Save cost center text area content to disk and return the file path."""
        content = self.cost_center_text.get("1.0", tk.END).strip()
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        self._cc_save_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self._cc_save_path

    def _validate_common(self) -> bool:
        """Validate common inputs. Returns True if valid."""
        month = self.month_var.get()
        year = self.year_var.get()
        if not (1 <= month <= 12):
            messagebox.showwarning("输入错误", "月份必须在 1-12 之间")
            return False
        if not (2020 <= year <= 2030):
            messagebox.showwarning("输入错误", "年份必须在 2020-2030 之间")
            return False
        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("输入错误", "请选择输出目录")
            return False
        return True

    def _common_kwargs(self) -> dict:
        """Build kwargs shared by both worker functions."""
        return {
            "month": self.month_var.get(),
            "year": self.year_var.get(),
            "output_dir": Path(self.output_dir_var.get()),
            "model": self._get_model(),
            "mapping_path": resource_path("报表科目.xlsx"),
            "prompt_path": resource_path("prompt.md"),
            "on_done": self._on_done,
        }

    def _on_download_and_generate(self) -> None:
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username or not password:
            messagebox.showwarning("输入错误", "请输入SAP用户名和密码")
            return
        if not self._validate_common():
            return
        cc_content = self.cost_center_text.get("1.0", tk.END).strip()
        if not cc_content:
            messagebox.showwarning("输入错误", "请输入至少一个成本中心")
            return

        self._clear_log()
        self._set_running(True)

        kwargs = self._common_kwargs()
        kwargs.update({
            "username": username,
            "password": password,
            "language": self.language_var.get(),
            "cost_center_file": self._save_cost_centers(),
        })
        threading.Thread(target=run_download_and_generate, kwargs=kwargs, daemon=True).start()

    def _on_generate_only(self) -> None:
        if not self._validate_common():
            return
        self._clear_log()
        self._set_running(True)

        threading.Thread(target=run_generate_only, kwargs=self._common_kwargs(), daemon=True).start()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
