"""Tests for the deterministic rule-based analysis in rules.py."""

from __future__ import annotations

from ksb1_accounting_check.rules import (
    MIN_ABS_DIFF,
    MIN_KEY_ELEMENT_DIFF,
    MIN_PCT_CHANGE,
    NOTE_CURR_ONLY,
    NOTE_PREV_ONLY,
    SKIP_KEMUS,
    _check_cost_element,
    _is_key_element,
    analyze_store,
)


# -- _is_key_element ----------------------------------------------------------


def test_is_key_element_exact_match():
    assert _is_key_element("电费")


def test_is_key_element_substring():
    assert _is_key_element("加拿大一店电费分摊")


def test_is_key_element_case_insensitive():
    assert _is_key_element("iot")
    assert _is_key_element("IOT")
    assert _is_key_element("opentable")
    assert _is_key_element("Opentable")


def test_is_key_element_non_match():
    assert not _is_key_element("办公用品")
    assert not _is_key_element("差旅费")


# -- _check_cost_element: Rule 1 — prev only ----------------------------------


def _detail(name="测试", prev=0.0, curr=0.0, diff=0.0, note=""):
    return {
        "成本要素名称": name,
        "上月金额": prev,
        "本月金额": curr,
        "差异": diff,
        "备注": note,
    }


def test_prev_only_generates_finding():
    d = _detail(name="电费", prev=1000.0, note=NOTE_PREV_ONLY)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is not None
    assert "12月有" in result["observation"]
    assert "1月无" in result["observation"]
    assert "电费" in result["observation"]


# -- _check_cost_element: Rule 2 — curr only ----------------------------------


def test_curr_only_generates_finding():
    d = _detail(name="清洁费", curr=2000.0, note=NOTE_CURR_ONLY)
    result = _check_cost_element("02、测试科目", d, 12, 1)
    assert result is not None
    assert "1月新增" in result["observation"]
    assert "12月无" in result["observation"]


# -- _check_cost_element: Rule 3 — key element diff ---------------------------


def test_key_element_above_threshold():
    diff = MIN_KEY_ELEMENT_DIFF + 100
    d = _detail(name="电费", prev=1000.0, curr=1000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is not None
    assert "多" in result["observation"]


def test_key_element_below_threshold():
    diff = MIN_KEY_ELEMENT_DIFF - 50
    d = _detail(name="电费", prev=1000.0, curr=1000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


def test_key_element_via_kemu_name():
    """Key element matched through kemu name, not cost element name."""
    d = _detail(name="某某费用", prev=1000.0, curr=1200.0, diff=200.0)
    result = _check_cost_element("电费科目", d, 12, 1)
    assert result is not None


# -- _check_cost_element: Rule 3 — non-key element diff -----------------------


def test_nonkey_above_both_thresholds():
    diff = MIN_ABS_DIFF + 100
    prev = 1000.0
    d = _detail(name="办公用品", prev=prev, curr=prev + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is not None
    assert "多" in result["observation"]


def test_nonkey_below_abs_threshold():
    diff = MIN_ABS_DIFF - 200
    d = _detail(name="办公用品", prev=1000.0, curr=1000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


def test_nonkey_below_pct_threshold():
    # diff > MIN_ABS_DIFF but pct < MIN_PCT_CHANGE
    diff = MIN_ABS_DIFF + 100
    prev = diff / (MIN_PCT_CHANGE / 2)  # pct = half the threshold
    d = _detail(name="办公用品", prev=prev, curr=prev + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


def test_nonkey_decrease():
    diff = -(MIN_ABS_DIFF + 500)
    d = _detail(name="办公用品", prev=2000.0, curr=2000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is not None
    assert "少" in result["observation"]


def test_nonkey_prev_zero_curr_nonzero():
    """When prev=0 and curr≠0, pct_change=inf — should trigger finding if above MIN_ABS_DIFF."""
    diff = MIN_ABS_DIFF + 100
    d = _detail(name="办公用品", prev=0.0, curr=diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is not None
    assert "多" in result["observation"]


def test_nonkey_prev_zero_curr_zero():
    """When both prev=0 and curr=0, no finding."""
    d = _detail(name="办公用品", prev=0.0, curr=0.0, diff=0.0)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


# -- _check_cost_element: no finding -------------------------------------------


def test_zero_diff_no_finding():
    d = _detail(name="办公用品", prev=1000.0, curr=1000.0, diff=0.0)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


# -- analyze_store -------------------------------------------------------------


def test_analyze_store_skips_kemus():
    """Kemus in SKIP_KEMUS should produce no findings."""
    for skip_kemu in SKIP_KEMUS:
        summary = [{
            "科目": skip_kemu,
            "上月金额": 10000.0,
            "本月金额": 0.0,
            "差异": -10000.0,
            "备注": "",
            "明细": [_detail(name="大额变动", prev=10000.0, curr=0.0, diff=-10000.0)],
        }]
        findings = analyze_store("测试店", 12, 1, summary)
        assert findings == [], f"Expected no findings for skipped kemu {skip_kemu}"


def test_analyze_store_multiple_kemus():
    summary = [
        {
            "科目": "01、测试A",
            "上月金额": 1000.0,
            "本月金额": 2000.0,
            "差异": 1000.0,
            "备注": "",
            "明细": [_detail(name="办公用品", prev=1000.0, curr=2000.0, diff=1000.0)],
        },
        {
            "科目": "02、测试B",
            "上月金额": 500.0,
            "本月金额": 500.0,
            "差异": 0.0,
            "备注": "",
            "明细": [_detail(name="其他", prev=500.0, curr=500.0, diff=0.0)],
        },
    ]
    findings = analyze_store("测试店", 12, 1, summary)
    assert len(findings) == 1
    assert "办公用品" in findings[0]["observation"]


def test_analyze_store_finding_structure():
    summary = [{
        "科目": "01、电费",
        "上月金额": 1000.0,
        "本月金额": 1500.0,
        "差异": 500.0,
        "备注": "",
        "明细": [_detail(name="电费", prev=1000.0, curr=1500.0, diff=500.0)],
    }]
    findings = analyze_store("测试店", 12, 1, summary)
    assert len(findings) == 1
    f = findings[0]
    assert "observation" in f
    assert "kemu_list" in f
    assert "cost_elements" in f
    assert f["kemu_list"] == ["01、电费"]
    assert f["cost_elements"] == ["电费"]
