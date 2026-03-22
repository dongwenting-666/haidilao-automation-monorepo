"""Tests for the deterministic rule-based analysis in rules.py."""

from __future__ import annotations

from ksb1_accounting_check.rules import (
    MIN_KEY_ELEMENT_DIFF,
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
    # curr_only builds "1月新增清洁费2.0K" — no "12月无" in this format
    assert "清洁费" in result["observation"]


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
# Non-key items present in both months are always skipped (normal fluctuation).


def test_nonkey_present_in_both_months_no_finding():
    """Non-key items present in both months are never reported (routine fluctuation)."""
    diff = 1100.0  # above MIN_ABS_DIFF
    prev = 1000.0
    d = _detail(name="办公用品", prev=prev, curr=prev + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None  # non-key, present in both months → silent


def test_nonkey_below_abs_threshold_no_finding():
    diff = 800.0  # below MIN_ABS_DIFF (1000)
    d = _detail(name="办公用品", prev=1000.0, curr=1000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None


def test_nonkey_decrease_no_finding():
    """Non-key items with decreases in both months are also silently dropped."""
    diff = -1500.0  # large abs diff but non-key
    d = _detail(name="办公用品", prev=2000.0, curr=2000.0 + diff, diff=diff)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None  # non-key, present in both months → silent


def test_nonkey_prev_zero_curr_nonzero_is_curr_only():
    """When prev=0 and curr>0, the note should be NOTE_CURR_ONLY, not an inline diff.

    The _check_cost_element function only sees the pre-computed 'note' field.
    When it is NOTE_CURR_ONLY it fires Rule 2 regardless of key status.
    """
    diff = 1100.0
    d = _detail(name="办公用品", prev=0.0, curr=diff, diff=diff, note=NOTE_CURR_ONLY)
    result = _check_cost_element("01、测试科目", d, 12, 1)
    # Non-key curr-only with abs ≥ MIN_KEY_ELEMENT_DIFF (200) generates a finding
    assert result is not None
    assert "新增" in result["observation"]


def test_nonkey_prev_zero_curr_nonzero_no_note():
    """When prev=0 and curr≠0 but note is empty (shouldn't normally happen).

    Rule 3 returns None for non-key items present in both months.
    Without a note, the item is treated as present-in-both.
    """
    diff = 1100.0
    d = _detail(name="办公用品", prev=0.0, curr=diff, diff=diff, note="")
    result = _check_cost_element("01、测试科目", d, 12, 1)
    assert result is None  # non-key, no note → treated as present in both → silent


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
    """Key-element 科目 with large change generates a finding; non-key does not."""
    summary = [
        {
            "科目": "01、电费",  # key kemu → large change triggers finding
            "上月金额": 1000.0,
            "本月金额": 2000.0,
            "差异": 1000.0,
            "备注": "",
            "明细": [_detail(name="电费", prev=1000.0, curr=2000.0, diff=1000.0)],
        },
        {
            "科目": "02、测试B",  # non-key, present in both → silent
            "上月金额": 500.0,
            "本月金额": 500.0,
            "差异": 0.0,
            "备注": "",
            "明细": [_detail(name="其他", prev=500.0, curr=500.0, diff=0.0)],
        },
    ]
    findings = analyze_store("测试店", 12, 1, summary)
    assert len(findings) == 1
    assert "电费" in findings[0]["observation"]


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
