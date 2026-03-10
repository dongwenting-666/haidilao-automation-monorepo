"""LLM enhancement for KSB1 accounting check — explains WHY rule-detected findings exist."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ollama_client import OllamaClient

log = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).resolve().parent / "prompt.md"


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _format_detail_rows(raw_rows: list[dict], prev_month: int, curr_month: int) -> str:
    """Format transaction detail rows with pre-computed subtotals for LLM.

    Groups rows by 名称 pattern within each month, computes subtotals,
    so the LLM doesn't need to do arithmetic.
    """
    # Group by (month, name) and compute subtotals
    groups: dict[tuple[int, str], float] = {}
    month_totals: dict[int, float] = {}
    for r in raw_rows:
        month = r.get("月份")
        if month is None:
            continue
        amt = r.get("对象货币值", 0)
        if not isinstance(amt, (int, float)):
            continue
        name = r.get("名称") or ""
        # Simplify name: take first meaningful segment for grouping
        short_name = _simplify_name(name)
        key = (month, short_name)
        groups[key] = groups.get(key, 0) + amt
        month_totals[month] = month_totals.get(month, 0) + amt

    # Build output: grouped subtotals by name across months
    all_names = sorted({name for (_, name) in groups})
    lines = []

    # Summary line
    p_total = month_totals.get(prev_month, 0)
    c_total = month_totals.get(curr_month, 0)
    lines.append(f"  合计: {prev_month}月={p_total:,.2f}  {curr_month}月={c_total:,.2f}  差异={c_total - p_total:,.2f}")

    # Per-name breakdown
    for name in all_names:
        p_amt = groups.get((prev_month, name), 0)
        c_amt = groups.get((curr_month, name), 0)
        diff = c_amt - p_amt
        if p_amt == 0 and c_amt == 0:
            continue
        p_count = sum(1 for r in raw_rows if r.get("月份") == prev_month and _simplify_name(r.get("名称") or "") == name)
        c_count = sum(1 for r in raw_rows if r.get("月份") == curr_month and _simplify_name(r.get("名称") or "") == name)
        lines.append(f"  {name}: {prev_month}月={p_amt:,.2f}({p_count}笔) {curr_month}月={c_amt:,.2f}({c_count}笔) 差异={diff:,.2f}")

    return "\n".join(lines)


def _simplify_name(name: str) -> str:
    """Simplify transaction name for grouping.

    Extracts the meaningful prefix — e.g., 'Salary for First half of Jan..-CA1D-Insurance'
    becomes 'Insurance', 'accrual 1D tax-EI January' becomes 'accrual tax-EI'.
    """
    if not name:
        return "(空)"
    # Keep it short but distinctive — truncate at 40 chars
    # Remove trailing month/date specifics for better grouping
    return name[:50]


def _build_enhance_prompt(
    store: str,
    prev_month: int,
    curr_month: int,
    findings_with_details: list[dict],
) -> str:
    """Build prompt for enhancing a batch of findings with detail rows."""
    blocks = []
    for item in findings_with_details:
        finding = item["finding"]
        details = item["detail_text"]
        block = f"异常: {finding['observation']}\n明细:\n{details}"
        blocks.append(block)

    return (
        f"门店: {store}\n"
        f"对比月份: {prev_month}月 vs {curr_month}月\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n请根据明细分析原因，增强每条observation，返回JSON数组。 /no_think"
    )


def create_client(model: str = "qwen3:8b") -> OllamaClient:
    """Create and return an OllamaClient."""
    return OllamaClient(model=model)


def enhance_findings(
    client: OllamaClient,
    store: str,
    prev_month: int,
    curr_month: int,
    findings: list[dict],
    kemu_rows: dict[str, list[dict]],
    max_retries: int = 2,
) -> list[dict]:
    """Enhance rule-detected findings with LLM-generated explanations.

    Takes findings from rules.analyze_store() and the raw transaction rows,
    sends them to the LLM for contextual explanation, and returns enhanced findings.

    Falls back to original findings if LLM fails.
    """
    if not findings:
        return findings

    system_prompt = _load_system_prompt()

    # Build detail text for each finding
    findings_with_details = []
    for finding in findings:
        cost_elements = finding.get("cost_elements", [])
        raw_rows = []
        if cost_elements:
            for rows in kemu_rows.values():
                for r in rows:
                    if r.get("成本要素名称") in cost_elements:
                        raw_rows.append(r)

        detail_text = _format_detail_rows(raw_rows, prev_month, curr_month) if raw_rows else "(无明细)"
        findings_with_details.append({"finding": finding, "detail_text": detail_text})

    # Batch findings to keep prompts manageable
    batches = _batch_findings(findings_with_details)
    log.info("  %s: enhancing %d findings in %d batches", store, len(findings), len(batches))

    enhanced = []
    for i, batch in enumerate(batches):
        batch_label = f"{store} batch {i + 1}/{len(batches)}"
        user_prompt = _build_enhance_prompt(store, prev_month, curr_month, batch)

        # Extract original findings for this batch (fallback)
        originals = [item["finding"] for item in batch]
        result = _call_llm(client, system_prompt, user_prompt, originals, batch_label, max_retries)
        enhanced.extend(result)

    return enhanced


def _batch_findings(
    findings_with_details: list[dict],
    max_chars: int = 4000,
) -> list[list[dict]]:
    """Split findings into batches that fit under max_chars."""
    batches = []
    current_batch = []
    current_size = 0

    for item in findings_with_details:
        item_size = len(item["finding"]["observation"]) + len(item["detail_text"])

        if current_batch and current_size + item_size > max_chars:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        current_batch.append(item)
        current_size += item_size + 10  # separator overhead

    if current_batch:
        batches.append(current_batch)

    return batches


def _call_llm(
    client: OllamaClient,
    system_prompt: str,
    user_prompt: str,
    originals: list[dict],
    label: str,
    max_retries: int,
) -> list[dict]:
    """Call LLM and parse response. Returns originals on failure."""
    for attempt in range(max_retries + 1):
        try:
            raw = client.generate(prompt=user_prompt, system=system_prompt).strip()
        except Exception as e:
            if attempt < max_retries:
                log.warning("LLM failed for %s (attempt %d): %s", label, attempt + 1, e)
                continue
            log.error("LLM failed for %s, using rule-based observations", label)
            return originals

        result = _parse_enhanced(raw, originals, label)
        if result is not None:
            return result
        if attempt < max_retries:
            log.warning("Parse failed for %s (attempt %d), retrying...", label, attempt + 1)

    log.warning("All attempts failed for %s, using rule-based observations", label)
    return originals


def _parse_enhanced(raw: str, originals: list[dict], label: str) -> list[dict] | None:
    """Parse LLM response, merging enhanced observations with original findings.

    Returns None on parse failure (caller should retry).
    """
    # Strip thinking tags
    if "<think>" in raw:
        think_end = raw.rfind("</think>")
        if think_end != -1:
            raw = raw[think_end + len("</think>"):].strip()

    # Strip markdown fences
    if "```" in raw:
        lines = raw.split("\n")
        cleaned = []
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not cleaned:
                cleaned.append(line)
        raw = "\n".join(cleaned).strip()

    # Find JSON array
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        log.warning("No JSON array in LLM response for %s", label)
        return None

    try:
        enhanced = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        log.warning("Failed to parse LLM JSON for %s: %s", label, e)
        return None

    if not isinstance(enhanced, list):
        return None

    # Merge: take enhanced observation, keep original kemu_list/cost_elements
    result = []
    for i, original in enumerate(originals):
        if i < len(enhanced) and isinstance(enhanced[i], dict) and "observation" in enhanced[i]:
            merged = original.copy()
            merged["observation"] = enhanced[i]["observation"]
            result.append(merged)
        else:
            result.append(original)

    return result
