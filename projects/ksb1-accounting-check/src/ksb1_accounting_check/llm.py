"""LLM-powered analysis for KSB1 accounting check via local Ollama."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ollama_client import OllamaClient

log = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).resolve().parent / "prompt.md"

# High-volume routine kemus — skip from LLM analysis entirely
SKIP_KEMUS = {"23、物料消耗", "33、资产折旧费", "15、员工餐费用"}


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _format_kemu_block(
    prev_month: int,
    curr_month: int,
    kemu_item: dict,
) -> str:
    """Format a single 科目 data block (without header/footer)."""
    kemu = kemu_item["科目"]
    prev_amt = kemu_item["上月金额"]
    curr_amt = kemu_item["本月金额"]
    diff = kemu_item["差异"]
    flag = kemu_item.get("备注", "")

    lines = [f"{kemu}: {prev_month}月={prev_amt:.2f}  {curr_month}月={curr_amt:.2f}  差异={diff:.2f}  {flag}"]

    sub_detail = kemu_item.get("明细", [])
    if len(sub_detail) > 1 or any(d.get("备注") for d in sub_detail):
        for d in sub_detail:
            name = d["成本要素名称"]
            p = d["上月金额"]
            c = d["本月金额"]
            dd = d["差异"]
            dn = d.get("备注", "")
            lines.append(f"  └ {name}: {prev_month}月={p:.2f} {curr_month}月={c:.2f} 差异={dd:.2f}  {dn}")

    return "\n".join(lines)


def _build_batch_prompt(
    store: str,
    prev_month: int,
    curr_month: int,
    kemu_batch: list[dict],
) -> str:
    """Build a prompt for a batch of 科目."""
    blocks = [_format_kemu_block(prev_month, curr_month, k) for k in kemu_batch]
    return (
        f"门店: {store}\n"
        f"对比月份: {prev_month}月 vs {curr_month}月\n\n"
        + "\n\n".join(blocks)
        + "\n\n请分析以上科目，找出异常，返回JSON数组。如无异常返回[]。 /no_think"
    )


def _batch_kemus(
    prev_month: int,
    curr_month: int,
    kemus: list[dict],
    max_chars: int = 800,
) -> list[list[dict]]:
    """Split kemus into batches that fit under max_chars per prompt body."""
    batches = []
    current_batch = []
    current_size = 0

    for k in kemus:
        block = _format_kemu_block(prev_month, curr_month, k)
        block_size = len(block)

        if current_batch and current_size + block_size > max_chars:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        current_batch.append(k)
        current_size += block_size + 2  # +2 for \n\n separator

    if current_batch:
        batches.append(current_batch)

    return batches


def create_client(model: str = "qwen3:8b") -> OllamaClient:
    """Create and return an OllamaClient (starts server + pulls model if needed)."""
    return OllamaClient(model=model)


def analyze_store(
    client: OllamaClient,
    store: str,
    prev_month: int,
    curr_month: int,
    kemu_summary: list[dict],
    max_retries: int = 2,
) -> list[dict]:
    """Analyze a store by running batched LLM calls.

    Kemus are batched into groups that fit within a size limit,
    then each batch is sent as one LLM call.

    Returns list of findings: [{"observation": "...", "kemu_list": ["..."]}]
    """
    system_prompt = _load_system_prompt()

    # Filter out skipped kemus
    kemus_to_analyze = [k for k in kemu_summary if k["科目"] not in SKIP_KEMUS]
    if not kemus_to_analyze:
        return []

    batches = _batch_kemus(prev_month, curr_month, kemus_to_analyze)
    log.info("  %s: %d kemus in %d batches", store, len(kemus_to_analyze), len(batches))

    all_findings = []
    for i, batch in enumerate(batches):
        batch_label = f"{store} batch {i + 1}/{len(batches)}"
        user_prompt = _build_batch_prompt(store, prev_month, curr_month, batch)

        for attempt in range(max_retries + 1):
            try:
                raw = client.generate(prompt=user_prompt, system=system_prompt).strip()
            except Exception as e:
                if attempt < max_retries:
                    log.warning("LLM failed for %s (attempt %d): %s", batch_label, attempt + 1, e)
                    continue
                log.error("LLM failed for %s after %d attempts: %s", batch_label, max_retries + 1, e)
                break

            result = _parse_findings(raw, batch_label)
            if result.success:
                all_findings.extend(result.findings)
                break
            if attempt < max_retries:
                log.warning("Parse failed for %s (attempt %d), retrying...", batch_label, attempt + 1)

    return all_findings


class _ParseResult:
    """Result of parsing LLM response, distinguishing valid empty from parse failure."""
    def __init__(self, findings: list[dict], success: bool):
        self.findings = findings
        self.success = success


def _parse_findings(raw: str, label: str) -> _ParseResult:
    """Parse LLM JSON response, handling markdown fences and thinking tags."""
    # Strip thinking tags if present (qwen3 uses <think>...</think>)
    if "<think>" in raw:
        think_end = raw.rfind("</think>")
        if think_end != -1:
            raw = raw[think_end + len("</think>"):].strip()

    # Strip markdown code fences
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
        log.warning("No JSON array found in LLM response for %s", label)
        return _ParseResult([], False)

    try:
        findings = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        log.warning("Failed to parse LLM JSON for %s: %s", label, e)
        return _ParseResult([], False)

    # Validate structure
    valid = []
    for f in findings:
        if isinstance(f, dict) and "observation" in f and "kemu_list" in f:
            # Ensure cost_elements exists (fallback to empty list)
            if "cost_elements" not in f:
                f["cost_elements"] = []
            valid.append(f)
    return _ParseResult(valid, True)
