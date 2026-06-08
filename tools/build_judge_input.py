#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Build blind judging artifacts from a test run directory.
Inputs read from the test run directory:
  - benchmark_results.jsonl
  - web_benchmark_results.jsonl
  - prompts JSON path passed on CLI
Output written to <test_run_dir>/judging:
  - judge_runbook_blind_a.md
  - judge_runbook_blind_b.md
  - judge_map.json
  - judging_prompts.txt
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from textwrap import dedent
from typing import Any, Dict, List, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _extract_turn_id(row: Dict[str, Any]) -> Optional[int]:
    tid = row.get("turn_id")
    if isinstance(tid, int):
        return tid
    case_id = row.get("case_id")
    if isinstance(case_id, str):
        m = re.search(r":turn:(\d+)$", case_id.strip())
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _resolve_prompts_json(prompts_json_path: str) -> str:
    p = os.path.abspath(prompts_json_path)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"prompts file not found: {p}")
    return p


@dataclass
class PromptTurn:
    """A single evaluation prompt turn paired with its grading rubric.

    Attributes:
        turn_id: Sequential turn identifier within the prompt set.
        prompt_text: The user prompt for the turn, or ``None`` when absent.
        rubric_id: Identifier of the rubric used to grade the turn, if any.
        rubric_text: The rubric body text used by the judge, if available.
    """

    turn_id: int
    prompt_text: Optional[str]
    rubric_id: Optional[str]
    rubric_text: Optional[str]


def _load_prompt_turns(prompts_json_path: str) -> tuple[Dict[int, PromptTurn], Dict[str, Any]]:
    with open(prompts_json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("prompts JSON must be a JSON object")

    turns_raw = payload.get("turns")
    if not isinstance(turns_raw, list):
        raise ValueError("prompts JSON must include a 'turns' array")

    turns: Dict[int, PromptTurn] = {}
    for item in turns_raw:
        if not isinstance(item, dict):
            continue
        tid = item.get("turn_id")
        if not isinstance(tid, int):
            continue
        turns[tid] = PromptTurn(
            turn_id=tid,
            prompt_text=item.get("prompt_text") if isinstance(item.get("prompt_text"), str) else None,
            rubric_id=item.get("rubric_id") if isinstance(item.get("rubric_id"), str) else None,
            rubric_text=item.get("rubric_text") if isinstance(item.get("rubric_text"), str) else None,
        )
    return turns, payload


def _index_by_turn(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        tid = _extract_turn_id(row)
        if tid is None:
            continue
        # First-seen wins for deterministic behavior.
        if tid not in out:
            out[tid] = row
    return out


def build_judge_rows(
    *,
    run_id: str,
    prompt_turns: Dict[int, PromptTurn],
    prompt_meta: Dict[str, Any],
    syx_rows: Dict[int, Dict[str, Any]],
    web_rows: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    turn_ids = sorted(set(prompt_turns.keys()) | set(syx_rows.keys()) | set(web_rows.keys()))
    system_prompt_text: Optional[str] = None
    sp = prompt_meta.get("system_prompt")
    if isinstance(sp, dict) and isinstance(sp.get("known_component"), str):
        system_prompt_text = str(sp.get("known_component"))

    results: List[Dict[str, Any]] = []
    for tid in turn_ids:
        p = prompt_turns.get(tid)
        mor = syx_rows.get(tid, {})
        web = web_rows.get(tid, {})

        candidate_a = mor.get("response_text") if isinstance(mor.get("response_text"), str) else None
        candidate_b = web.get("response_text") if isinstance(web.get("response_text"), str) else None

        missing_fields: List[str] = []
        if not candidate_a:
            missing_fields.append("candidate_a")
        if not candidate_b:
            missing_fields.append("candidate_b")
        if not (p and p.rubric_text):
            missing_fields.append("rubric_text")

        row: Dict[str, Any] = {
            "ts": _utc_iso(),
            "run_id": run_id,
            "benchmark_name": prompt_meta.get("benchmark_name") if isinstance(prompt_meta.get("benchmark_name"), str) else None,
            "turn_id": int(tid),
            "prompt_text": (p.prompt_text if p else None),
            "rubric_id": (p.rubric_id if p else None),
            "rubric_text": (p.rubric_text if p else None),
            "system_prompt_known_component": system_prompt_text,
            "candidate_a": candidate_a,  # fixed mapping: Syx response
            "candidate_b": candidate_b,  # fixed mapping: Web/ChatGPT response
            "candidate_a_case_id": mor.get("case_id"),
            "candidate_b_case_id": web.get("case_id"),
            "candidate_a_source": "benchmark_results.jsonl",
            "candidate_b_source": "web_benchmark_results.jsonl",
            "completeness": ("full" if not missing_fields else "partial"),
            "missing_fields": missing_fields,
        }
        results.append(row)
    return results


def _build_blind_runbook_md(
    *,
    run_id: str,
    blind_batch: str,
    samples: List[Dict[str, Any]],
    scores_path: str,
) -> str:
    if blind_batch not in {"blind_a", "blind_b"}:
        raise ValueError("blind_batch must be 'blind_a' or 'blind_b'")

    prefix = "a" if blind_batch == "blind_a" else "b"
    scores_filename = f"{prefix}_benchmark_scores_<model_slug>.jsonl"

    header = dedent(
        f"""\
        # Judge Runbook ({blind_batch})

        - run_id: `{run_id}`
        - generated_at_utc: `{_utc_iso()}`
        - blind_batch: `{blind_batch}`
        - output_scores_file_template: `{scores_filename}`
        - output_scores_path_example: `{scores_path}`

        ## How To Use

        - Run this runbook in a fresh chat to minimize cross-step context effects.
        - Keep judge instructions fixed across models.
        - Process steps in order. Each step evaluates exactly one response sample.
        - For each step, return strict JSON only.
        - Use a normalized model slug in the output filename (lowercase, letters/numbers/underscores only).
        - Append one JSON object per step to `{scores_filename}` in the same directory as this runbook.

        ## Fixed Judge Instructions

        Use these exact instructions for each step:

        ```text
            You are an impartial benchmark judge.

            Evaluate the provided response independently against the rubric for this single case.

            Rules:
            - Use only the provided prompt_text, rubric_text, and response_text.
            - Do not use outside knowledge or assumptions.
            - Score the response using the rubric as an absolute standard, not relative to other responses.
            - Assign subscores first, then overall score.
            - Do not reward style unless the rubric explicitly asks for it.
            - Do not reduce any score because of line-break, whitespace, or paragraph-formatting artifacts introduced by text extraction unless they make the response meaningfully harder to understand.
            - If the response remains clear and fully comprehensible, extraction artifacts alone must not lower Clarity from 5 to 4.
            - Score Clarity based on organization, specificity, and ease of understanding of the ideas, not on cosmetic formatting damage from extraction.
            - Score each rubric criterion on a 1-5 scale using these anchors:
                - 5 = fully satisfies the criterion with no meaningful weakness
                - 4 = strong, with one noticeable weakness
                - 3 = adequate, with multiple weaknesses
                - 2 = weak or partially incomplete
                - 1 = poor, missing, or seriously flawed
            - A score of 5 is not reserved for a single best answer in the batch.
            - Assign a 5 whenever the response fully satisfies the rubric and any weaknesses are minor.
            - Many responses across the benchmark may legitimately earn 5.
            - Do not lower a score merely to preserve separation from other responses.

            - Overall score should reflect rubric performance of this response alone.
            - Do not compare against prior responses when assigning overall score.
            - If the response is strong across all criteria and only has minor weaknesses, overall 5 is appropriate.

            - Return strict JSON only. No markdown, no prose outside JSON.

            Required JSON keys:
            - sample_id
            - subscores
            - overall
            - rationale
        ```

        ## Steps
        """
    )

    step_blocks: List[str] = []
    for step_num, sample in enumerate(samples, start=1):
        case_payload = {
            "sample_id": sample.get("sample_id"),
            "prompt_text": sample.get("prompt_text"),
            "rubric_text": sample.get("rubric_text"),
            "response_text": sample.get("response_text"),
        }
        output_shape = {
            "run_id": run_id,
            "sample_id": sample.get("sample_id"),
            "scorer_model": "<fill-in>",
            "scorer_run_id": "<fill-in>",
            "subscores": {"<criterion_name>": "<1-5>"},
            "overall": "<1-5>",
            "rationale": "<short rubric-grounded explanation>",
        }
        case_json = json.dumps(case_payload, ensure_ascii=False, indent=2)
        output_json = json.dumps(output_shape, ensure_ascii=False, indent=2)
        step_blocks.append(
            f"""### Step {step_num}: Evaluate sample {sample.get('sample_id')}

Case input:

```json
{case_json}
```

Expected output shape (strict JSON only):

```json
{output_json}
```

After generating this JSON, append it as one line to `{scores_path}`.
"""
        )

    completion = dedent(
        f"""\
        ## Completion

        - When all steps are done, `{scores_path}` should contain one JSON line per sample in this runbook.
        - Re-run this same runbook with a different model for fair comparison.
        """
    )

    return f"{header}\n{'\n'.join(step_blocks)}\n{completion}".strip()


def _sample_id(index_1_based: int) -> str:
    return f"S{index_1_based:03d}"


def _build_judging_prompts_text(
    *,
    runbook_a_path: str,
    runbook_b_path: str,
    judging_dir: str,
) -> str:
    prompt_a = dedent(
        f"""\
        Use @{runbook_a_path} as the only workflow.
        Follow all steps in order.
        For each step, produce strict JSON only for that sample.
        Append one JSON line per step to `{os.path.join(judging_dir, "a_benchmark_scores_<model_slug>.jsonl")}`.
        Do not skip steps.
        """
    ).strip()

    prompt_b = dedent(
        f"""\
        Use @{runbook_b_path} as the only workflow.
        Follow all steps in order.
        For each step, produce strict JSON only for that sample.
        Append one JSON line per step to `{os.path.join(judging_dir, "b_benchmark_scores_<model_slug>.jsonl")}`.
        Do not skip steps.
        """
    ).strip()

    return (
        "Prompt 1 (blind_a)\n"
        "------------------\n"
        f"{prompt_a}\n\n"
        "Prompt 2 (blind_b)\n"
        "------------------\n"
        f"{prompt_b}\n"
    )


def run(test_run_dir: str, prompts_json_path: str) -> int:
    test_run_dir = os.path.abspath(test_run_dir)
    if not os.path.isdir(test_run_dir):
        raise FileNotFoundError(f"test run directory not found: {test_run_dir}")

    benchmark_path = os.path.join(test_run_dir, "benchmark_results.jsonl")
    web_benchmark_path = os.path.join(test_run_dir, "web_benchmark_results.jsonl")
    if not os.path.isfile(benchmark_path):
        raise FileNotFoundError(f"missing file: {benchmark_path}")
    if not os.path.isfile(web_benchmark_path):
        raise FileNotFoundError(f"missing file: {web_benchmark_path}")

    prompts_path = _resolve_prompts_json(prompts_json_path)
    prompt_turns, prompt_meta = _load_prompt_turns(prompts_path)

    syx_rows = _index_by_turn(_read_jsonl(benchmark_path))
    web_rows = _index_by_turn(_read_jsonl(web_benchmark_path))

    run_id = os.path.basename(test_run_dir.rstrip(os.sep))
    judge_rows = build_judge_rows(
        run_id=run_id,
        prompt_turns=prompt_turns,
        prompt_meta=prompt_meta,
        syx_rows=syx_rows,
        web_rows=web_rows,
    )
    if not judge_rows:
        raise ValueError("no judge rows produced")

    judging_dir = os.path.join(test_run_dir, "judging")
    os.makedirs(judging_dir, exist_ok=True)

    blind_a_samples: List[Dict[str, Any]] = []
    blind_b_samples: List[Dict[str, Any]] = []
    map_rows: List[Dict[str, Any]] = []
    sample_index = 1

    for row in judge_rows:
        for blind_batch, candidate_label, case_id_key, source_key in (
            ("blind_a", "candidate_a", "candidate_a_case_id", "candidate_a_source"),
            ("blind_b", "candidate_b", "candidate_b_case_id", "candidate_b_source"),
        ):
            sid = _sample_id(sample_index)
            sample_index += 1

            sample_payload = {
                "sample_id": sid,
                "prompt_text": row.get("prompt_text"),
                "rubric_text": row.get("rubric_text"),
                "response_text": row.get(candidate_label),
            }
            if blind_batch == "blind_a":
                blind_a_samples.append(sample_payload)
            else:
                blind_b_samples.append(sample_payload)

            map_rows.append(
                {
                    "sample_id": sid,
                    "run_id": run_id,
                    "blind_batch": blind_batch,
                    "true_candidate_label": candidate_label,
                    "turn_id": row.get("turn_id"),
                    "candidate_case_id": row.get(case_id_key),
                    "source_file": row.get(source_key),
                    "created_at": _utc_iso(),
                }
            )

    map_path = os.path.join(judging_dir, "judge_map.json")
    map_payload = {
        "run_id": run_id,
        "generated_at_utc": _utc_iso(),
        "samples": map_rows,
    }
    with open(map_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(map_payload, ensure_ascii=False, indent=2) + "\n")

    runbook_a_path = os.path.join(judging_dir, "judge_runbook_blind_a.md")
    scores_a_path = os.path.join(judging_dir, "a_benchmark_scores_<model_slug>.jsonl")
    runbook_a_text = _build_blind_runbook_md(
        run_id=run_id,
        blind_batch="blind_a",
        samples=blind_a_samples,
        scores_path=scores_a_path,
    )
    with open(runbook_a_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(runbook_a_text + "\n")

    runbook_b_path = os.path.join(judging_dir, "judge_runbook_blind_b.md")
    scores_b_path = os.path.join(judging_dir, "b_benchmark_scores_<model_slug>.jsonl")
    runbook_b_text = _build_blind_runbook_md(
        run_id=run_id,
        blind_batch="blind_b",
        samples=blind_b_samples,
        scores_path=scores_b_path,
    )
    with open(runbook_b_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(runbook_b_text + "\n")

    prompts_path = os.path.join(judging_dir, "judging_prompts.txt")
    prompts_text = _build_judging_prompts_text(
        runbook_a_path=runbook_a_path,
        runbook_b_path=runbook_b_path,
        judging_dir=judging_dir,
    )
    with open(prompts_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(prompts_text)

    print(f"Wrote {len(blind_a_samples)} samples to {runbook_a_path}")
    print(f"Wrote {len(blind_b_samples)} samples to {runbook_b_path}")
    print(f"Wrote mapping file to {map_path}")
    print(f"Wrote copy/paste prompts to {prompts_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build blind judging artifacts from benchmark outputs.")
    parser.add_argument("test_run_dir", help="Path to test_run directory")
    parser.add_argument("prompts_json", help="Path to prompts JSON file")
    args = parser.parse_args()
    try:
        return run(args.test_run_dir, args.prompts_json)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

