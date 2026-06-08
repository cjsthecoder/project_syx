#!/usr/bin/env python3
"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Build benchmark_turns.csv from turns.jsonl and web_turns.jsonl.
Output format:
- Label
- Syx Part 1
- Syx Part 2
- Web Part 1
- Web Part 2
"""

import argparse
import csv
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _parse_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                logger.warning("Skipping invalid JSONL at %s:%s: %s", path, line_no, exc)
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _build_syx_map(turns_path: str) -> dict[int, tuple[int, int]]:
    rows = _read_jsonl(turns_path)
    out: dict[int, tuple[int, int]] = {}

    for row in rows:
        if row.get("event") != "end_turn":
            continue
        turn_id = _parse_int(row.get("turn_id"))
        if turn_id is None:
            continue
        main_prompt = _parse_int(row.get("main_prompt_tokens_reported"))
        mini_prompt = _parse_int(row.get("mini_prompt_tokens_reported"))
        if mini_prompt is None:
            # Backward compatibility for historical runs written before the split.
            mini_prompt = _parse_int(row.get("mini_total_tokens_reported_sum"))
        syx_main = int(main_prompt or 0)
        syx_mini = int(mini_prompt or 0)
        out[turn_id] = (syx_main, syx_mini)
    return out


def _build_web_map(web_turns_path: str) -> dict[int, tuple[int, int]]:
    rows = _read_jsonl(web_turns_path)
    out: dict[int, tuple[int, int]] = {}

    for row in rows:
        turn_id = _parse_int(row.get("turn_id"))
        if turn_id is None:
            continue
        prompt_system = _parse_int(row.get("prompt_system_tokens_est"))
        prompt_profile = _parse_int(row.get("prompt_profile_tokens_est"))
        prompt_other = _parse_int(row.get("prompt_other_tokens_est"))
        prompt_history = _parse_int(row.get("prompt_history_tokens_est"))
        web_turn = int((prompt_system or 0) + (prompt_profile or 0) + (prompt_other or 0))
        web_context = int(prompt_history or 0)
        out[turn_id] = (web_turn, web_context)
    return out


def _main() -> int:
    parser = argparse.ArgumentParser(description="Build benchmark_turns.csv from run JSONL artifacts.")
    parser.add_argument(
        "--test-run-dir",
        required=True,
        help="Path to backend/runs/test_run_* directory.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="CSV output path (default: <test-run-dir>/benchmark_turns.csv).",
    )
    args = parser.parse_args()

    test_run_dir = os.path.abspath(args.test_run_dir)
    turns_path = os.path.join(test_run_dir, "turns.jsonl")
    web_turns_path = os.path.join(test_run_dir, "web_turns.jsonl")
    output_path = os.path.abspath(args.output) if args.output else os.path.join(test_run_dir, "benchmark_turns.csv")

    if not os.path.isdir(test_run_dir):
        raise FileNotFoundError(f"test-run-dir does not exist: {test_run_dir}")
    if not os.path.isfile(turns_path):
        raise FileNotFoundError(f"turns.jsonl not found: {turns_path}")

    output_parent = os.path.dirname(output_path)
    if output_parent and not os.path.isdir(output_parent):
        raise FileNotFoundError(f"output directory does not exist: {output_parent}")

    syx = _build_syx_map(turns_path)
    web = _build_web_map(web_turns_path) if os.path.isfile(web_turns_path) else {}
    all_turn_ids = sorted(set(syx.keys()) | set(web.keys()))
    if not all_turn_ids:
        raise RuntimeError("No usable turn rows found in input files.")

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Label", "Syx Part 1", "Syx Part 2", "Web Part 1", "Web Part 2"])
        for turn_id in all_turn_ids:
            m_main, m_mini = syx.get(turn_id, (0, 0))
            w_turn, w_ctx = web.get(turn_id, (0, 0))
            writer.writerow([turn_id, m_main, m_mini, w_turn, w_ctx])

    print(f"Wrote {len(all_turn_ids)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
