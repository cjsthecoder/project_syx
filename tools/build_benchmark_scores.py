#!/usr/bin/env python3
"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

Build per-turn average benchmark score CSV for blind batch A and/or B.

Behavior:
- read score files for selected batch(es), e.g. b_benchmark_scores_*.jsonl
- map each sample_id -> turn_id via judge_map.json
- choose a per-row score source:
  - provided: use row["overall"]
  - recomputed: mean of numeric values in row["subscores"]
- average the chosen score per turn across scorer models
- write one-column CSV (no header) with one row per turn
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
from typing import Any


def _parse_score(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _score_from_subscores(row: dict[str, Any]) -> float | None:
    subscores = row.get("subscores")
    if not isinstance(subscores, dict):
        return None

    values: list[float] = []
    for value in subscores.values():
        parsed = _parse_score(value)
        if parsed is not None:
            values.append(parsed)
    if not values:
        return None
    return sum(values) / len(values)


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at: {path}")
    return payload


def _load_json_objects(path: str) -> list[dict[str, Any]]:
    """
    Load a file containing a sequence of JSON objects.

    Supports:
    - strict JSONL (one object per line)
    - pretty-printed/multi-line JSON objects concatenated in a file
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, next_idx = decoder.raw_decode(text, idx)
        except Exception as exc:
            snippet = text[idx : min(idx + 120, length)].replace("\n", "\\n")
            raise ValueError(f"Invalid JSON object in {path} near: {snippet}") from exc
        if isinstance(obj, dict):
            rows.append(obj)
        idx = next_idx
    return rows


def _collect_score_files(judging_dir: str, batch: str) -> list[str]:
    prefix = "a" if batch == "A" else "b"
    pattern = os.path.join(judging_dir, f"{prefix}_benchmark_scores_*.jsonl")
    files = sorted(glob.glob(pattern))
    return files


def _build_sample_turn_map(judge_map_path: str, batch: str) -> dict[str, int]:
    payload = _load_json(judge_map_path)
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError(f"'samples' missing or not a list in {judge_map_path}")

    expected_blind_batch = "blind_a" if batch == "A" else "blind_b"
    out: dict[str, int] = {}
    for item in samples:
        if not isinstance(item, dict):
            continue
        sample_id = item.get("sample_id")
        turn_id = item.get("turn_id")
        blind_batch = item.get("blind_batch")
        if (
            isinstance(sample_id, str)
            and isinstance(turn_id, int)
            and isinstance(blind_batch, str)
            and blind_batch == expected_blind_batch
        ):
            out[sample_id] = turn_id
    return out


def _build_csv_for_batch(
    *,
    test_run_dir: str,
    judging_dir: str,
    judge_map_path: str,
    batch: str,
    output_path: str,
    overall_source: str,
) -> None:
    sample_turn_map = _build_sample_turn_map(judge_map_path, batch)
    score_files = _collect_score_files(judging_dir, batch)
    if not score_files:
        raise FileNotFoundError(f"No score files found for batch {batch} under: {judging_dir}")

    turn_scores: dict[int, list[float]] = {}
    seen: set[tuple[str, str]] = set()
    duplicate_scores_skipped = 0
    invalid_rows_skipped = 0

    for score_file in score_files:
        rows = _load_json_objects(score_file)
        for row in rows:
            sample_id = row.get("sample_id")
            if not isinstance(sample_id, str):
                continue

            turn_id = sample_turn_map.get(sample_id)
            if turn_id is None:
                continue

            if overall_source == "provided":
                score = _parse_score(row.get("overall"))
            else:
                score = _score_from_subscores(row)
            if score is None:
                invalid_rows_skipped += 1
                continue

            scorer_model = row.get("scorer_model")
            scorer_model_norm = (
                scorer_model.strip() if isinstance(scorer_model, str) and scorer_model.strip() else "unknown"
            )
            dedupe_key = (scorer_model_norm, sample_id)
            if dedupe_key in seen:
                duplicate_scores_skipped += 1
                continue
            seen.add(dedupe_key)

            if turn_id not in turn_scores:
                turn_scores[turn_id] = []
            turn_scores[turn_id].append(score)

    if not turn_scores:
        raise RuntimeError(f"No turn scores collected for batch {batch}.")

    turn_ids = sorted(turn_scores.keys())
    rows: list[list[str]] = []
    for turn_id in turn_ids:
        scores = turn_scores[turn_id]
        avg = sum(scores) / len(scores)
        rows.append([f"{avg:.4f}"])

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"[{batch}] Wrote {len(rows)} rows to {output_path}")
    print(f"[{batch}] overall_source={overall_source}")
    print(f"[{batch}] duplicate_scores_skipped={duplicate_scores_skipped}")
    print(f"[{batch}] invalid_rows_skipped={invalid_rows_skipped}")


def _build_combined_csv(
    *,
    test_run_dir: str,
    judging_dir: str,
    judge_map_path: str,
    output_path: str,
    overall_source: str,
) -> None:
    batch_values: dict[str, dict[int, str]] = {}
    for batch in ("A", "B"):
        sample_turn_map = _build_sample_turn_map(judge_map_path, batch)
        score_files = _collect_score_files(judging_dir, batch)
        if not score_files:
            raise FileNotFoundError(f"No score files found for batch {batch} under: {judging_dir}")

        turn_scores: dict[int, list[float]] = {}
        seen: set[tuple[str, str]] = set()
        duplicate_scores_skipped = 0
        invalid_rows_skipped = 0

        for score_file in score_files:
            rows = _load_json_objects(score_file)
            for row in rows:
                sample_id = row.get("sample_id")
                if not isinstance(sample_id, str):
                    continue

                turn_id = sample_turn_map.get(sample_id)
                if turn_id is None:
                    continue

                if overall_source == "provided":
                    score = _parse_score(row.get("overall"))
                else:
                    score = _score_from_subscores(row)
                if score is None:
                    invalid_rows_skipped += 1
                    continue

                scorer_model = row.get("scorer_model")
                scorer_model_norm = (
                    scorer_model.strip() if isinstance(scorer_model, str) and scorer_model.strip() else "unknown"
                )
                dedupe_key = (scorer_model_norm, sample_id)
                if dedupe_key in seen:
                    duplicate_scores_skipped += 1
                    continue
                seen.add(dedupe_key)

                if turn_id not in turn_scores:
                    turn_scores[turn_id] = []
                turn_scores[turn_id].append(score)

        if not turn_scores:
            raise RuntimeError(f"No turn scores collected for batch {batch}.")

        batch_values[batch] = {}
        for turn_id in sorted(turn_scores.keys()):
            scores = turn_scores[turn_id]
            avg = sum(scores) / len(scores)
            batch_values[batch][turn_id] = f"{avg:.4f}"

        print(f"[{batch}] overall_source={overall_source}")
        print(f"[{batch}] duplicate_scores_skipped={duplicate_scores_skipped}")
        print(f"[{batch}] invalid_rows_skipped={invalid_rows_skipped}")

    all_turns = sorted(set(batch_values["A"].keys()) | set(batch_values["B"].keys()))
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["A", "B"])
        for turn_id in all_turns:
            writer.writerow([
                batch_values["A"].get(turn_id, ""),
                batch_values["B"].get(turn_id, ""),
            ])

    print(f"[A+B] Wrote {len(all_turns)} rows to {output_path}")


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Build per-turn average CSV from blind judge score files."
    )
    parser.add_argument(
        "--test-run-dir",
        required=True,
        help="Path to backend/runs/test_run_* directory.",
    )
    parser.add_argument(
        "--batch",
        choices=["A", "B", "BOTH"],
        required=True,
        help="Blind batch to process.",
    )
    parser.add_argument(
        "--overall-source",
        choices=["provided", "recomputed"],
        default="provided",
        help="Use row overall directly, or recompute from subscores.",
    )
    parser.add_argument("--output", default=None, help="CSV output path.")
    args = parser.parse_args()

    test_run_dir = os.path.abspath(args.test_run_dir)
    judging_dir = os.path.join(test_run_dir, "judging")
    judge_map_path = os.path.join(judging_dir, "judge_map.json")

    if not os.path.isdir(test_run_dir):
        raise FileNotFoundError(f"test-run-dir does not exist: {test_run_dir}")
    if not os.path.isdir(judging_dir):
        raise FileNotFoundError(f"judging dir does not exist: {judging_dir}")
    if not os.path.isfile(judge_map_path):
        raise FileNotFoundError(f"judge_map.json not found: {judge_map_path}")

    if args.batch == "BOTH":
        output_path = os.path.abspath(args.output) if args.output else os.path.join(test_run_dir, "benchmark_scores.csv")
        output_parent = os.path.dirname(output_path)
        if output_parent and not os.path.isdir(output_parent):
            raise FileNotFoundError(f"output directory does not exist: {output_parent}")
        _build_combined_csv(
            test_run_dir=test_run_dir,
            judging_dir=judging_dir,
            judge_map_path=judge_map_path,
            output_path=output_path,
            overall_source=args.overall_source,
        )
    else:
        output_filename_default = f"benchmark_scores_{args.batch}.csv"
        output_path = os.path.abspath(args.output) if args.output else os.path.join(test_run_dir, output_filename_default)
        output_parent = os.path.dirname(output_path)
        if output_parent and not os.path.isdir(output_parent):
            raise FileNotFoundError(f"output directory does not exist: {output_parent}")

        _build_csv_for_batch(
            test_run_dir=test_run_dir,
            judging_dir=judging_dir,
            judge_map_path=judge_map_path,
            batch=args.batch,
            output_path=output_path,
            overall_source=args.overall_source,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
