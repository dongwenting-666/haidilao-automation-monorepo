"""Rule-based analysis for KSB1 accounting check — deterministic, no LLM."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# High-volume routine kemus — skip from analysis entirely.
# These are payroll/insurance items that fluctuate naturally month-to-month
# and aren't what the manual check focuses on.
SKIP_KEMUS = {
    "23、物料消耗",
    "33、资产折旧费",
    "15、员工餐费用",
    "14、员工社保费",        # routine insurance
    "正式工工资",            # handled at kemu level, not per-element
    "钟点工工资",            # handled at kemu level
    "35、装修费摊销",        # fixed amortization
}

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
MIN_ABS_DIFF = 1000          # Ignore non-key differences under 1000 CAD
MIN_KEY_ELEMENT_DIFF = 200   # Key elements: report changes above 200 CAD
MIN_PCT_CHANGE = 0.30        # 30% change threshold for non-key items


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

    Produces concise observations matching manual report style:
    - Key items missing this month (暂未计提/报销)
    - Key items that doubled (两个月都在X月报了)
    - Significant amount changes for key cost elements
    - Cross-store charge detection

    Returns list of findings: [{"observation": "...", "kemu_list": [...], "cost_elements": [...]}]
    """
    findings = []

    for kemu_item in kemu_summary:
        kemu = kemu_item["科目"]
        if kemu in SKIP_KEMUS:
            continue

        # Kemu-level: detect missing key items (whole category gone)
        if _is_key_element(kemu):
            kemu_finding = _check_kemu_level(kemu, kemu_item, prev_month, curr_month)
            if kemu_finding:
                findings.append(kemu_finding)
                continue  # don't also report per-element if kemu-level covers it

        for detail in kemu_item.get("明细", []):
            finding = _check_cost_element(kemu, detail, prev_month, curr_month)
            if finding:
                findings.append(finding)

    # Cross-store charge detection
    if all_rows:
        cross_store = _check_cross_store_charges(store, all_rows, curr_month)
        if cross_store:
            findings.append(cross_store)

    log.info("  %s: %d findings from rules", store, len(findings))
    return findings


def _check_kemu_level(
    kemu: str,
    kemu_item: dict,
    prev_month: int,
    curr_month: int,
) -> dict | None:
    """Check a whole 科目 category for key patterns the manual report flags.

    Detects:
    - Key category entirely missing this month → "X月暂未计提Y"
    - Key category entirely missing last month → "X月Y费用补报/新增"
    - Key category doubled → "两个月的Y都在X月报了"
    """
    prev_amt = kemu_item["上月金额"]
    curr_amt = kemu_item["本月金额"]
    note = kemu_item.get("备注", "")

    # Strip number prefix for cleaner display: "210、电费" → "电费"
    display = kemu.split("、")[-1] if "、" in kemu else kemu

    if note == NOTE_PREV_ONLY:
        return _finding(f"{curr_month}月暂未计提{display}", kemu, display)

    if note == NOTE_CURR_ONLY:
        if abs(curr_amt) >= MIN_KEY_ELEMENT_DIFF:
            amt_str = _fmt_short_amt(curr_amt)
            return _finding(f"{curr_month}月新增{display}{amt_str}", kemu, display)

    # Doubled: current month is roughly 2x the expected (prev_amt as baseline)
    if prev_amt != 0 and curr_amt != 0:
        ratio = curr_amt / prev_amt
        if ratio > 1.8 and abs(curr_amt - prev_amt) >= 1000:
            return _finding(
                f"两个月的{display}可能都在{curr_month}月报了（{curr_month}月是{prev_month}月的{ratio:.1f}倍）",
                kemu, display,
            )
        if ratio < 0.2 and abs(prev_amt - curr_amt) >= 1000:
            return _finding(
                f"两个月的{display}可能都在{prev_month}月报了（{prev_month}月是{curr_month}月的{1/ratio:.1f}倍）",
                kemu, display,
            )

    return None


def _fmt_short_amt(amt: float) -> str:
    """Format amount concisely: 5000 → 5K, 300 → 300."""
    abs_amt = abs(amt)
    if abs_amt >= 1000:
        return f"{abs_amt/1000:.1f}K".rstrip("0").rstrip(".")
    return f"{abs_amt:.0f}"


# Cost element name keywords that are routine and shouldn't generate findings
# unless they're completely absent. These fluctuate naturally month-to-month.
_ROUTINE_KEYWORDS = [
    "退休金", "工伤保险", "员工保险", "雇主健康税", "健康服务保险",
    "联邦政府税", "魁北克政府税", "职能部门费用分摊",
]
_ROUTINE_KEYWORDS_LOWER = [kw.lower() for kw in _ROUTINE_KEYWORDS]


def _is_routine(name: str) -> bool:
    name_lower = name.lower()
    return any(kw in name_lower for kw in _ROUTINE_KEYWORDS_LOWER)


def _check_cost_element(
    kemu: str,
    detail: dict,
    prev_month: int,
    curr_month: int,
) -> dict | None:
    """Check a single cost element against rules. Returns a finding or None."""
    name = detail["成本要素名称"]

    # Skip routine payroll/insurance sub-items — they fluctuate naturally
    if _is_routine(name):
        return None
    prev_amt = detail["上月金额"]
    curr_amt = detail["本月金额"]
    diff = detail["差异"]
    note = detail.get("备注", "")
    is_key = _is_key_element(name) or _is_key_element(kemu)

    # Rule 1: Present last month, absent this month
    if note == NOTE_PREV_ONLY:
        # Only report if the missing amount is meaningful
        if abs(prev_amt) < MIN_KEY_ELEMENT_DIFF and not is_key:
            return None
        return _finding(
            f"{curr_month}月无{name}（{prev_month}月有{_fmt_short_amt(prev_amt)}）",
            kemu, name,
        )

    # Rule 2: New this month
    if note == NOTE_CURR_ONLY:
        if abs(curr_amt) < MIN_KEY_ELEMENT_DIFF and not is_key:
            return None
        return _finding(
            f"{curr_month}月新增{name}{_fmt_short_amt(curr_amt)}",
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
