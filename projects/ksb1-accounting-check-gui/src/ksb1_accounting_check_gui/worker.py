"""Background worker for SAP download and report generation."""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# User-friendly error messages for known exceptions
_ERROR_MESSAGES = {
    "SAPConnectionError": (
        "SAP GUI 未连接。请确认：\n"
        "  1. SAP GUI 已打开\n"
        "  2. 已登录到 SAP 系统\n"
        "  3. SAP GUI Scripting 已启用"
    ),
    "SAPNavigationError": (
        "SAP 操作失败。请确认：\n"
        "  1. SAP 界面没有弹出其他窗口\n"
        "  2. 当前没有其他正在运行的事务"
    ),
    "SAPExportError": (
        "SAP 导出失败。请确认：\n"
        "  1. 输出目录可写\n"
        "  2. 文件没有被其他程序占用"
    ),
    "SAPStatusBarError": "SAP 报错，请检查 SAP 状态栏的错误信息。",
    "OllamaConnectionError": (
        "Ollama 连接失败。请确认：\n"
        "  1. 已安装 Ollama (https://ollama.com)\n"
        "  2. 或者留空「模型」字段，仅使用规则分析"
    ),
}


def _friendly_error(e: Exception) -> str:
    """Convert exception to user-friendly Chinese error message."""
    cls_name = type(e).__name__
    if cls_name in _ERROR_MESSAGES:
        hint = _ERROR_MESSAGES[cls_name]
        return f"{hint}\n\n原始错误: {e}"
    if isinstance(e, FileNotFoundError):
        return f"文件未找到: {e}"
    if isinstance(e, PermissionError):
        return f"权限不足，文件可能被占用: {e}"
    return f"发生错误: {e}"


def _month_range(year: int, month: int) -> tuple[date, date]:
    """Return (first_day_of_prev_month, last_day_of_month)."""
    if month == 1:
        prev_start = date(year - 1, 12, 1)
    else:
        prev_start = date(year, month - 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    curr_end = date(year, month, last_day)
    return prev_start, curr_end


def _common_generate_kwargs(
    month: int,
    year: int,
    output_dir: Path,
    model: str | None,
    mapping_path: Path,
    prompt_path: Path,
) -> dict:
    """Build shared kwargs for _generate()."""
    year_month = f"{year}-{month:02d}"
    out = output_dir / year_month
    timestamp = datetime.now().strftime("%H%M%S")
    return {
        "year_month": year_month,
        "out": out,
        "ksb1_path": out / f"ksb1-{year_month}.XLSX",
        "report_path": out / f"{year_month}_KSB1_检查报告_{timestamp}.XLSX",
        "month": month,
        "model": model,
        "mapping_path": mapping_path,
        "prompt_path": prompt_path,
    }


def run_download_and_generate(
    username: str,
    password: str,
    month: int,
    year: int,
    output_dir: Path,
    language: str,
    model: str | None,
    mapping_path: Path,
    cost_center_file: Path,
    prompt_path: Path,
    on_done: Callable[[bool, str], None],
) -> None:
    """Download KSB1 from SAP and generate report. Runs in a background thread."""
    try:
        if not mapping_path.exists():
            raise FileNotFoundError(f"报表科目映射文件未找到: {mapping_path}")
        if not cost_center_file.exists():
            raise FileNotFoundError(f"成本中心文件未找到: {cost_center_file}")

        kwargs = _common_generate_kwargs(month, year, output_dir, model, mapping_path, prompt_path)
        date_from, date_to = _month_range(year, month)

        # Step 1: Download from SAP
        from sap_gui.processes.ksb1 import run as ksb1_export

        log.info("正在从SAP下载KSB1 (%s, %s 至 %s)...", kwargs["year_month"], date_from, date_to)
        ksb1_export(
            username=username,
            password=password,
            cost_center_file=cost_center_file,
            output_path=kwargs["ksb1_path"],
            date_from=date_from,
            date_to=date_to,
            language=language,
        )

        # Step 2: Generate report
        _generate(
            ksb1_path=kwargs["ksb1_path"],
            report_path=kwargs["report_path"],
            month=kwargs["month"],
            model=kwargs["model"],
            mapping_path=kwargs["mapping_path"],
            prompt_path=kwargs["prompt_path"],
        )
        on_done(True, str(kwargs["report_path"]))

    except Exception as e:
        msg = _friendly_error(e)
        log.error(msg)
        on_done(False, msg)


def run_generate_only(
    month: int,
    year: int,
    output_dir: Path,
    model: str | None,
    mapping_path: Path,
    prompt_path: Path,
    on_done: Callable[[bool, str], None],
) -> None:
    """Generate report from existing KSB1 file. Runs in a background thread."""
    try:
        kwargs = _common_generate_kwargs(month, year, output_dir, model, mapping_path, prompt_path)
        ksb1_path = kwargs["ksb1_path"]

        if not ksb1_path.exists():
            raise FileNotFoundError(
                f"KSB1 文件未找到: {ksb1_path}\n"
                f"请先用「下载 SAP 数据 + 生成报告」按钮下载数据，\n"
                f"或确认 {kwargs['out']} 目录下有 ksb1-{kwargs['year_month']}.XLSX 文件。"
            )
        if not mapping_path.exists():
            raise FileNotFoundError(f"报表科目映射文件未找到: {mapping_path}")

        log.info("使用已有KSB1文件: %s", ksb1_path)

        _generate(
            ksb1_path=ksb1_path,
            report_path=kwargs["report_path"],
            month=kwargs["month"],
            model=kwargs["model"],
            mapping_path=kwargs["mapping_path"],
            prompt_path=kwargs["prompt_path"],
        )
        on_done(True, str(kwargs["report_path"]))

    except Exception as e:
        msg = _friendly_error(e)
        log.error(msg)
        on_done(False, msg)


def _generate(
    ksb1_path: Path,
    report_path: Path,
    month: int,
    model: str | None,
    mapping_path: Path,
    prompt_path: Path,
) -> None:
    """Shared report generation logic."""
    from ksb1_accounting_check.analyze import generate_report

    log.info("正在生成检查报告...")
    generate_report(
        ksb1_path=ksb1_path,
        output_path=report_path,
        target_month=month,
        mapping_path=mapping_path,
        model=model,
        prompt_path=prompt_path,
    )
    log.info("完成！报告已保存至 %s", report_path)
