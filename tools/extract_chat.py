#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Extract USER/ASSISTANT pairs from ChatGPT HTML exports and emit benchmark JSONL.
"""

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup
import tiktoken


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("extract_chat")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(str(text or "")))


def load_system_prompt_from_benchmark_json(prompts_json_path: str) -> tuple[str, int]:
    """
    Load benchmark system prompt text and its token estimate.
    """
    try:
        with open(prompts_json_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception as exc:
        raise ValueError(f"Failed to read prompts JSON '{prompts_json_path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("prompts JSON root must be an object")
    sp = payload.get("system_prompt")
    if not isinstance(sp, dict):
        return "", 0
    text = sp.get("known_component")
    if not isinstance(text, str):
        return "", 0
    text_value = str(text)
    return text_value, int(estimate_tokens(text_value))


def load_profile_prompt_from_benchmark_json(prompts_json_path: str) -> tuple[str, int]:
    """
    Load benchmark profile prompt text and its token estimate.
    """
    try:
        with open(prompts_json_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception as exc:
        raise ValueError(f"Failed to read prompts JSON '{prompts_json_path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("prompts JSON root must be an object")
    pp = payload.get("profile_prompt")
    if not isinstance(pp, dict):
        return "", 0
    text = pp.get("known_component")
    if not isinstance(text, str):
        return "", 0
    text_value = str(text)
    return text_value, int(estimate_tokens(text_value))


def parse_html_file(html_file: str) -> Optional[BeautifulSoup]:
    logger.info("Starting extraction from: %s", html_file)
    try:
        with open(html_file, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file, "html.parser")
        logger.info("Successfully parsed HTML with BeautifulSoup")
        return soup
    except Exception as exc:
        logger.error("Error reading HTML file: %s", exc, exc_info=True)
        return None


def extract_messages_from_soup(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Extract ordered role/text messages using ChatGPT HTML role attribute.
    """
    messages: list[tuple[str, str]] = []
    try:
        logger.info("Searching for conversation messages...")
        for div in soup.find_all("div", attrs={"data-message-author-role": True}):
            role = str(div.get("data-message-author-role") or "").upper().strip()
            if role not in {"USER", "ASSISTANT"}:
                continue
            text = div.get_text(strip=True)
            if text:
                messages.append((role, text))
        logger.info("Found %s role-tagged messages", len(messages))
    except Exception as exc:
        logger.error("Error parsing role-tagged messages: %s", exc, exc_info=True)
        return []
    return messages


def extract_messages_fallback(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Fallback parser when role-tagged divs are unavailable.
    """
    messages: list[tuple[str, str]] = []
    try:
        logger.warning("No role-tagged messages found. Trying fallback parsing.")
        all_text = soup.get_text(separator="\n")
        user_matches = re.findall(
            r"User:\s*(.*?)(?=Assistant:|$)",
            all_text,
            re.DOTALL | re.IGNORECASE,
        )
        assistant_matches = re.findall(
            r"Assistant:\s*(.*?)(?=User:|$)",
            all_text,
            re.DOTALL | re.IGNORECASE,
        )
        for match in user_matches:
            if match:
                messages.append(("USER", match))
        for match in assistant_matches:
            if match:
                messages.append(("ASSISTANT", match))
        logger.info("Fallback found %s messages", len(messages))
    except Exception as exc:
        logger.error("Error in fallback parsing: %s", exc, exc_info=True)
        return []
    return messages


def pair_turns(messages: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """
    Pair each USER message with the next ASSISTANT message.
    """
    pairs: list[tuple[str, str]] = []
    stats = {
        "orphan_assistant": 0,
        "replaced_unanswered_user": 0,
        "trailing_unanswered_user": 0,
    }
    pending_user: Optional[str] = None

    for role, text in messages:
        if role == "USER":
            if pending_user is not None:
                stats["replaced_unanswered_user"] += 1
            pending_user = text
            continue
        # ASSISTANT
        if pending_user is None:
            stats["orphan_assistant"] += 1
            continue
        pairs.append((pending_user, text))
        pending_user = None

    if pending_user is not None:
        stats["trailing_unanswered_user"] += 1

    return pairs, stats


def build_benchmark_record(
    *,
    case_id: str,
    prompt_text: str,
    response_text: str,
    timestamp: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "case_id": case_id,
        "system": "chatgpt",
        "model_id": None,
        "timestamp": timestamp,
        "prompt_text": prompt_text,
        "response_text": response_text,
        "run_id": None,
        "turn_id": None,
        "main_total_tokens_reported": None,
        "turn_total_tokens_reported": None,
        "latency_ms": None,
        "metrics_source": "html_extracted",
        "completeness": "partial",
        "missing_fields": [
            "model_id",
            "run_id",
            "turn_id",
            "main_total_tokens_reported",
            "turn_total_tokens_reported",
            "latency_ms",
        ],
    }
    return record


def validate_benchmark_record(record: dict[str, Any]) -> tuple[bool, list[str]]:
    required_keys = [
        "case_id",
        "system",
        "model_id",
        "timestamp",
        "prompt_text",
        "response_text",
        "run_id",
        "turn_id",
        "main_total_tokens_reported",
        "turn_total_tokens_reported",
        "latency_ms",
        "metrics_source",
        "completeness",
        "missing_fields",
    ]
    missing = [k for k in required_keys if k not in record]
    return (len(missing) == 0, missing)


def validate_web_turn_record(record: dict[str, Any]) -> tuple[bool, list[str]]:
    required_keys = [
        "ts",
        "event",
        "run_id",
        "turn_id",
        "prompt_system_tokens_est",
        "prompt_history_tokens_est",
        "prompt_rag_tokens_est",
        "prompt_profile_tokens_est",
        "prompt_other_tokens_est",
        "route",
        "rag_enabled",
        "retrieved_count",
        "kept_count",
        "expanded_unique_chunks_after_merge",
        "final_context_tokens_est",
        "final_context_clipped",
        "main_total_tokens_reported",
        "mini_prompt_tokens_reported",
        "mini_completion_tokens_reported",
        "turn_total_tokens_reported",
        "turn_usage_source",
        "turn_usage_is_estimate",
        "provider_tokens_total",
        "estimated_tokens_total",
        "zero_fallback_tokens_total",
        "ttfb_ms_main",
        "ttlt_ms_main",
        "ttlt_ms_turn_total",
        "invocations_count_total",
        "main_invocations_count",
        "mini_invocations_count",
        "main_prompt_tokens_reported",
        "main_completion_tokens_reported",
    ]
    missing = [k for k in required_keys if k not in record]
    if missing:
        return False, missing

    prompt_sum = (
        int(record["prompt_system_tokens_est"])
        + int(record["prompt_history_tokens_est"])
        + int(record["prompt_rag_tokens_est"])
        + int(record["prompt_profile_tokens_est"])
        + int(record["prompt_other_tokens_est"])
    )
    if int(record["final_context_tokens_est"]) != prompt_sum:
        return False, ["final_context_tokens_est(prompt_sum_mismatch)"]

    total_expected = int(record["main_total_tokens_reported"]) + int(record["mini_prompt_tokens_reported"])
    if int(record["turn_total_tokens_reported"]) != total_expected:
        return False, ["turn_total_tokens_reported(total_mismatch)"]

    decomp_expected = int(record["main_prompt_tokens_reported"]) + int(record["main_completion_tokens_reported"])
    if int(record["main_total_tokens_reported"]) != decomp_expected:
        return False, ["main_total_tokens_reported(prompt_completion_mismatch)"]

    inv_expected = int(record["main_invocations_count"]) + int(record["mini_invocations_count"])
    if int(record["invocations_count_total"]) != inv_expected:
        return False, ["invocations_count_total(counter_mismatch)"]

    return True, []


def output_benchmark_path_for_run_dir(test_run_path: str) -> str:
    run_dir = os.path.abspath(test_run_path)
    return os.path.join(run_dir, "web_benchmark_results.jsonl")


def output_web_turns_path_for_run_dir(test_run_path: str) -> str:
    run_dir = os.path.abspath(test_run_path)
    return os.path.join(run_dir, "web_turns.jsonl")


def validate_inputs(prompts_json_path: str, input_file: str, test_run_path: str) -> None:
    if not os.path.exists(prompts_json_path):
        raise FileNotFoundError(f"prompts_json not found: {prompts_json_path}")
    prompt_ext = os.path.splitext(prompts_json_path)[1].lower()
    if prompt_ext != ".json":
        raise ValueError(f"Unsupported prompts_json extension '{prompt_ext}'. Expected .json")
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"File not found: {input_file}")
    ext = os.path.splitext(input_file)[1].lower()
    if ext not in {".html", ".htm"}:
        raise ValueError(f"Unsupported file extension '{ext}'. Expected .html/.htm")
    if not os.path.exists(test_run_path):
        raise FileNotFoundError(f"test_run_path not found: {test_run_path}")
    if not os.path.isdir(test_run_path):
        raise ValueError(f"test_run_path is not a directory: {test_run_path}")


def run(prompts_json_path: str, input_file: str, test_run_path: str) -> int:
    try:
        validate_inputs(prompts_json_path, input_file, test_run_path)
    except Exception as exc:
        logger.error("%s", exc)
        return 1

    try:
        system_prompt_text, system_prompt_tokens = load_system_prompt_from_benchmark_json(prompts_json_path)
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    try:
        profile_prompt_text, profile_prompt_tokens = load_profile_prompt_from_benchmark_json(prompts_json_path)
    except Exception as exc:
        logger.error("%s", exc)
        return 1

    # Persist benchmark prompt definition as a run artifact.
    try:
        dst_path = os.path.join(os.path.abspath(test_run_path), os.path.basename(prompts_json_path))
        shutil.copy2(prompts_json_path, dst_path)
        logger.info("Copied prompts artifact to %s", dst_path)
    except Exception as exc:
        logger.error("Failed to copy prompts artifact: %s", exc, exc_info=True)
        return 1

    soup = parse_html_file(input_file)
    if soup is None:
        return 1

    messages = extract_messages_from_soup(soup)
    if not messages:
        messages = extract_messages_fallback(soup)
    if not messages:
        logger.error("No messages found in input HTML.")
        return 1

    pairs, pair_stats = pair_turns(messages)
    if not pairs:
        logger.error("No valid USER->ASSISTANT pairs found.")
        return 1

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    run_id = os.path.basename(os.path.abspath(test_run_path).rstrip(os.sep))
    records: list[dict[str, Any]] = []
    web_turn_records: list[dict[str, Any]] = []
    invalid_count = 0
    invalid_web_turn_count = 0
    history_text_parts: list[str] = []
    sum_context_tokens = 0
    sum_main_total_tokens = 0
    for idx, (prompt_text, response_text) in enumerate(pairs, start=1):
        case_id = f"{base_name}:turn:{idx}"
        prompt_other_tokens_est = int(estimate_tokens(prompt_text))
        prompt_history_tokens_est = int(estimate_tokens("\n".join(history_text_parts))) if history_text_parts else 0
        prompt_system_tokens_est = int(system_prompt_tokens)
        prompt_profile_tokens_est = int(profile_prompt_tokens)
        prompt_rag_tokens_est = 0
        final_context_tokens_est = int(
            prompt_system_tokens_est
            + prompt_history_tokens_est
            + prompt_rag_tokens_est
            + prompt_profile_tokens_est
            + prompt_other_tokens_est
        )
        response_tokens = int(estimate_tokens(response_text))
        main_total_tokens_reported = int(final_context_tokens_est + response_tokens)
        latency_ms_raw = None
        ttlt_ms_main = int(latency_ms_raw or 0)

        record = build_benchmark_record(
            case_id=case_id,
            prompt_text=prompt_text,
            response_text=response_text,
            timestamp=_utc_iso(),
        )
        valid, missing = validate_benchmark_record(record)
        if not valid:
            invalid_count += 1
            logger.warning("Skipping invalid record case_id=%s missing_keys=%s", case_id, missing)
            continue

        web_turn_record = {
            "ts": _utc_iso(),
            "event": "end_turn",
            "system": "chatgpt_web",
            "run_id": run_id,
            "turn_id": int(idx),
            "prompt_system_tokens_est": int(prompt_system_tokens_est),
            "prompt_history_tokens_est": int(prompt_history_tokens_est),
            "prompt_rag_tokens_est": int(prompt_rag_tokens_est),
            "prompt_profile_tokens_est": int(prompt_profile_tokens_est),
            "prompt_other_tokens_est": int(prompt_other_tokens_est),
            "route": "OTHER",
            "rag_enabled": False,
            "retrieved_count": 0,
            "kept_count": 0,
            "expanded_unique_chunks_after_merge": 0,
            "final_context_tokens_est": int(final_context_tokens_est),
            "final_context_clipped": False,
            "main_total_tokens_reported": int(main_total_tokens_reported),
            "mini_prompt_tokens_reported": 0,
            "mini_completion_tokens_reported": 0,
            "turn_total_tokens_reported": int(main_total_tokens_reported),
            "main_prompt_tokens_reported": int(final_context_tokens_est),
            "main_completion_tokens_reported": int(response_tokens),
            "turn_usage_source": "estimate",
            "turn_usage_is_estimate": True,
            "provider_tokens_total": 0,
            "estimated_tokens_total": int(main_total_tokens_reported),
            "zero_fallback_tokens_total": 0,
            "ttfb_ms_main": None,
            "ttlt_ms_main": int(ttlt_ms_main),
            "ttlt_ms_turn_total": int(ttlt_ms_main),
            "invocations_count_total": 1,
            "main_invocations_count": 1,
            "mini_invocations_count": 0,
        }
        web_valid, web_missing = validate_web_turn_record(web_turn_record)
        if not web_valid:
            invalid_web_turn_count += 1
            logger.warning("Skipping invalid web_turn record turn_id=%s issues=%s", idx, web_missing)
            continue

        records.append(record)
        web_turn_records.append(web_turn_record)
        sum_context_tokens += int(final_context_tokens_est)
        sum_main_total_tokens += int(main_total_tokens_reported)
        history_text_parts.append(prompt_text)
        history_text_parts.append(response_text)

    if not records or not web_turn_records:
        logger.error("No valid benchmark/web_turn records produced.")
        return 1

    out_path = output_benchmark_path_for_run_dir(test_run_path)
    web_turns_out_path = output_web_turns_path_for_run_dir(test_run_path)
    try:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fp:
            for rec in records:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(web_turns_out_path, "w", encoding="utf-8", newline="\n") as fp:
            for rec in web_turn_records:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error(
            "Failed writing output files '%s'/'%s': %s",
            out_path,
            web_turns_out_path,
            exc,
            exc_info=True,
        )
        return 1

    logger.info("Wrote %s benchmark records to %s", len(records), out_path)
    logger.info("Wrote %s synthetic web_turn records to %s", len(web_turn_records), web_turns_out_path)
    logger.info(
        "Extraction stats: messages=%s pairs=%s invalid_records=%s invalid_web_turn_records=%s orphan_assistant=%s replaced_unanswered_user=%s trailing_unanswered_user=%s system_prompt_tokens=%s profile_prompt_tokens=%s total_context_tokens=%s total_main_tokens=%s",
        len(messages),
        len(pairs),
        invalid_count,
        invalid_web_turn_count,
        pair_stats["orphan_assistant"],
        pair_stats["replaced_unanswered_user"],
        pair_stats["trailing_unanswered_user"],
        system_prompt_tokens,
        profile_prompt_tokens,
        sum_context_tokens,
        sum_main_total_tokens,
    )
    return 0


def main() -> int:
    if len(sys.argv) != 4:
        logger.error("Usage: python3 extract_chat.py <prompts.json> <chat_export.html> <test_run_path>")
        return 1
    return run(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    sys.exit(main())
