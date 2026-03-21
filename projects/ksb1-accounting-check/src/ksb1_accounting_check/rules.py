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
    """Build concise observation like '多电费5K' or '少保险费530'.

    Matches the manual report style: terse, one-line, easy to scan.
    """
    abs_diff = abs(diff)
    direction = "多" if diff > 0 else "少"

    # Abbreviate large amounts: 5000 → 5K, 12000 → 12K
    if abs_diff >= 1000:
        amt_str = f"{abs_diff/1000:.1f}K".rstrip("0").rstrip(".")
    else:
        amt_str = f"{abs_diff:.0f}"

    pct = _fmt_pct(prev_amt, curr_amt)
    return f"{curr_month}月{direction}{name}{amt_str}{pct}"


def analyze_store(
    store: str,
    prev_month: int,
    curr_month: int,
    kemu_summary: list[dict],
    all_rows: list[dict] | None = None,
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

    # Cross-store charge detection: flag transactions where 名称 mentions
    # a different store than the one being analyzed
    if all_rows:
        cross_store = _check_cross_store_charges(store, all_rows, curr_month)
        if cross_store:
            findings.append(cross_store)

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
        if abs(prev_amt) >= 1000:
            amt_str = f"{abs(prev_amt)/1000:.1f}K".rstrip("0").rstrip(".")
        else:
            amt_str = f"{abs(prev_amt):.0f}"
        return _finding(
            f"{prev_month}月有{name}{amt_str}，{curr_month}月无",
            kemu, name,
        )

    # Rule 2: New this month
    if note == NOTE_CURR_ONLY:
        if abs(curr_amt) >= 1000:
            amt_str = f"{abs(curr_amt)/1000:.1f}K".rstrip("0").rstrip(".")
        else:
            amt_str = f"{abs(curr_amt):.0f}"
        return _finding(
            f"{curr_month}月新增{name}{amt_str}",
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


# Store name keywords for cross-store detection
_STORE_KEYWORDS = {
    "1D": "一店", "2D": "二店", "3D": "三店", "4D": "四店",
    "5D": "五店", "6D": "六店", "7D": "七店", "8D": "八店",
    "CA1D": "一店", "CA2D": "二店", "CA3D": "三店", "CA4D": "四店",
    "CA5D": "五店", "CA6D": "六店", "CA7D": "七店", "CA8D": "八店",
    "一店": "一店", "二店": "二店", "三店": "三店", "四店": "四店",
    "五店": "五店", "六店": "六店", "七店": "七店", "八店": "八店",
}


def _check_cross_store_charges(
    store: str, rows: list[dict], curr_month: int,
) -> dict | None:
    """Detect transactions charged to this store that mention a different store."""
    # Determine which store number this is
    own_store = None
    for kw, name in _STORE_KEYWORDS.items():
        if name in store or kw in store:
            own_store = name
            break
    if not own_store:
        return None

    cross_charges = []
    for r in rows:
        if r.get("月份") != curr_month:
            continue
        desc = str(r.get("名称") or "") + str(r.get("物料描述") or "")
        for kw, name in _STORE_KEYWORDS.items():
            if name == own_store:
                continue
            if kw in desc:
                amt = r.get("对象货币值", 0)
                cross_charges.append(f"{name}({kw}): {_fmt_amt(amt)} - {r.get('名称','')[:40]}")
                break

    if not cross_charges:
        return None

    obs = f"⚠️ 发现{len(cross_charges)}笔疑似非本店消费:\n" + "\n".join(cross_charges[:5])
    if len(cross_charges) > 5:
        obs += f"\n...及另外{len(cross_charges)-5}笔"

    return {
        "observation": obs,
        "kemu_list": [],
        "cost_elements": [],
    }
