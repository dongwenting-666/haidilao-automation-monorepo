"""Rule-based analysis for KSB1 accounting check — deterministic, no LLM."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# High-volume routine kemus — skip from analysis entirely
SKIP_KEMUS = {"23、物料消耗", "33、资产折旧费", "15、员工餐费用"}

# Sentinel note strings (shared with analyze.py)
NOTE_PREV_ONLY = "上月有本月无"
NOTE_CURR_ONLY = "本月有上月无"

# Cost element name keywords that are always reported when they change
# (matched case-insensitively as substring against 成本要素名称)
KEY_COST_ELEMENTS = [
    "电费", "车辆保险", "清洁费", "燃料费", "燃气费", "税",
    "财产保险", "保险费", "咨询服务", "租赁费", "房租", "宿舍租赁",
    "水电气", "水费", "宿舍水电燃", "工资", "IOT", "Opentable", "神秘嘉宾",
]
_KEY_COST_ELEMENTS_LOWER = [kw.lower() for kw in KEY_COST_ELEMENTS]

# Thresholds for "significant difference"
MIN_ABS_DIFF = 500           # Ignore differences under 500 CAD
MIN_KEY_ELEMENT_DIFF = 100   # Key elements: report changes above 100 CAD
MIN_PCT_CHANGE = 0.20        # 20% change threshold for non-key items


def _is_key_element(name: str) -> bool:
    """Check if a cost element name matches any key element keyword."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in _KEY_COST_ELEMENTS_LOWER)


def _fmt_amt(amt: float) -> str:
    """Format amount with 2 decimal places."""
    return f"{amt:,.2f}"


def _fmt_pct(prev: float, curr: float) -> str:
    """Format percentage change string."""
    if prev == 0:
        return ""
    pct = (curr - prev) / abs(prev) * 100
    return f"（{'增加' if pct > 0 else '减少'}{abs(pct):.1f}%）"


def _fmt_diff_obs(
    name: str, prev_month: int, curr_month: int,
    diff: float, prev_amt: float, curr_amt: float,
) -> str:
    """Build '多/少 X CAD (Y%)' observation string."""
    abs_diff = abs(diff)
    pct = _fmt_pct(prev_amt, curr_amt)
    direction = "多" if diff > 0 else "少"
    return f"{name}{curr_month}月比{prev_month}月{direction}{_fmt_amt(abs_diff)}{pct}"


def analyze_store(
    store: str,
    prev_month: int,
    curr_month: int,
    kemu_summary: list[dict],
) -> list[dict]:
    """Analyze a store using deterministic rules.

    Returns list of findings: [{"observation": "...", "kemu_list": [...], "cost_elements": [...]}]
    """
    findings = []

    for kemu_item in kemu_summary:
        kemu = kemu_item["科目"]
        if kemu in SKIP_KEMUS:
            continue

        for detail in kemu_item.get("明细", []):
            finding = _check_cost_element(kemu, detail, prev_month, curr_month)
            if finding:
                findings.append(finding)

    log.info("  %s: %d findings from rules", store, len(findings))
    return findings


def _check_cost_element(
    kemu: str,
    detail: dict,
    prev_month: int,
    curr_month: int,
) -> dict | None:
    """Check a single cost element against rules. Returns a finding or None."""
    name = detail["成本要素名称"]
    prev_amt = detail["上月金额"]
    curr_amt = detail["本月金额"]
    diff = detail["差异"]
    note = detail.get("备注", "")
    is_key = _is_key_element(name) or _is_key_element(kemu)

    # Rule 1: Present last month, absent this month
    if note == NOTE_PREV_ONLY:
        return _finding(
            f"{name}{prev_month}月有{_fmt_amt(prev_amt)}CAD，{curr_month}月无",
            kemu, name,
        )

    # Rule 2: New this month
    if note == NOTE_CURR_ONLY:
        return _finding(
            f"{name}{curr_month}月新增{_fmt_amt(curr_amt)}CAD，{prev_month}月无",
            kemu, name,
        )

    # Rule 3: Amount difference checks
    abs_diff = abs(diff)
    if abs_diff < MIN_ABS_DIFF and not is_key:
        return None

    # Key elements: always report above minimal threshold
    if is_key and abs_diff >= MIN_KEY_ELEMENT_DIFF:
        return _finding(
            _fmt_diff_obs(name, prev_month, curr_month, diff, prev_amt, curr_amt),
            kemu, name,
        )

    # Non-key elements: report if above both absolute and percentage thresholds
    pct_change = abs(diff) / abs(prev_amt) if prev_amt != 0 else (float("inf") if curr_amt != 0 else 0)
    if abs_diff >= MIN_ABS_DIFF and pct_change >= MIN_PCT_CHANGE:
        return _finding(
            _fmt_diff_obs(name, prev_month, curr_month, diff, prev_amt, curr_amt),
            kemu, name,
        )

    return None


def _finding(observation: str, kemu: str, cost_element: str) -> dict:
    return {
        "observation": observation,
        "kemu_list": [kemu],
        "cost_elements": [cost_element],
    }
