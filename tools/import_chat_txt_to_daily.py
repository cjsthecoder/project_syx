#!/usr/bin/env python3
"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

Import pre-tagged chat TXT files into an output directory.

Behavior:
- Input is a directory containing top-level .txt files (no recursion).
- Copy each .txt to output directory.
- If target name exists, append suffixes like _1, _2, ... before extension.
- Append one per-file statistics row to output statistics.jsonl.
- Write one concatenated output file for this run: concatenated_daily.txt.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger("import_chat_txt_to_daily")

USER_MARKER = "--- USER (data-message-author-role: user) ---"
ASSISTANT_MARKER = "*** ASSISTANT (data-message-author-role: assistant) ***"


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _require_tiktoken() -> Any:
    try:
        import tiktoken  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'tiktoken'. Install backend dependencies before running this tool."
        ) from exc
    return tiktoken


def _validate_input_dir(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Input path is not a directory: {path}")


def _validate_output_dir(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Output directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Output path is not a directory: {path}")


def _iter_input_txt_files(input_dir: Path) -> list[Path]:
    return [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]


def _destination_with_suffix(output_dir: Path, src_name: str) -> Path:
    candidate = output_dir / src_name
    if not candidate.exists():
        return candidate
    stem = Path(src_name).stem
    suffix = Path(src_name).suffix
    idx = 1
    while True:
        candidate = output_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def _count_pairs_from_markers(text: str) -> tuple[int, dict[str, int]]:
    pattern = re.compile(
        rf"({re.escape(USER_MARKER)}|{re.escape(ASSISTANT_MARKER)})",
        flags=re.MULTILINE,
    )
    tokens = [m.group(1) for m in pattern.finditer(text)]

    pairs = 0
    orphan_assistant = 0
    replaced_unanswered_user = 0
    pending_user = False

    for tok in tokens:
        if tok == USER_MARKER:
            if pending_user:
                replaced_unanswered_user += 1
            pending_user = True
            continue
        # ASSISTANT marker
        if not pending_user:
            orphan_assistant += 1
            continue
        pairs += 1
        pending_user = False

    trailing_unanswered_user = 1 if pending_user else 0
    return pairs, {
        "orphan_assistant": orphan_assistant,
        "replaced_unanswered_user": replaced_unanswered_user,
        "trailing_unanswered_user": trailing_unanswered_user,
    }


def _estimate_tokens(text: str, enc: Any) -> int:
    return len(enc.encode(str(text or "")))


def _append_statistics(
    *,
    output_dir: Path,
    filename_root: str,
    file_path: Path,
    pairs_total: int,
    tokens_total: int,
    pairing_stats: dict[str, int],
) -> None:
    stats_path = output_dir / "statistics.jsonl"
    record = {
        "ts": datetime.now().isoformat(),
        "filename_root": filename_root,
        # Requested: input/output can be the same for this txt-import tool.
        "input_file": str(file_path),
        "output_file": str(file_path),
        "pairs_total": int(pairs_total),
        # Requested: both token fields are the same overall total for this tool.
        "tokens_user_assistant_total_est": int(tokens_total),
        "tokens_output_total_est": int(tokens_total),
        "timestamp_source": "txt_import",
        "pairing_stats": pairing_stats,
    }
    with open(stats_path, "a", encoding="utf-8", newline="\n") as sf:
        sf.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_concatenated_output(output_dir: Path, copied_files: list[Path]) -> Path:
    concat_path = output_dir / "concatenated_daily.txt"
    parts: list[str] = []
    for p in copied_files:
        try:
            parts.append(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed reading copied file '{p}': {exc}") from exc
    combined = "\n".join(part.rstrip() for part in parts) + "\n"
    try:
        concat_path.write_text(combined, encoding="utf-8", newline="\n")
    except Exception as exc:
        raise RuntimeError(f"Failed writing '{concat_path}': {exc}") from exc
    return concat_path


def run(input_dir_raw: str, output_dir_raw: str) -> int:
    _setup_logging()
    input_dir = Path(input_dir_raw).resolve()
    output_dir = Path(output_dir_raw).resolve()

    _validate_input_dir(input_dir)
    _validate_output_dir(output_dir)

    tiktoken = _require_tiktoken()
    enc = tiktoken.get_encoding("cl100k_base")

    input_files = _iter_input_txt_files(input_dir)
    if not input_files:
        raise RuntimeError(f"No .txt files found in input directory: {input_dir}")

    copied_files: list[Path] = []
    failed_count = 0
    for src in input_files:
        try:
            raw_text = src.read_text(encoding="utf-8")
            pairs_total, pairing_stats = _count_pairs_from_markers(raw_text)
            tokens_total = _estimate_tokens(raw_text, enc)

            dst = _destination_with_suffix(output_dir, src.name)
            shutil.copy2(src, dst)
            copied_files.append(dst)

            _append_statistics(
                output_dir=output_dir,
                filename_root=dst.stem,
                file_path=dst,
                pairs_total=pairs_total,
                tokens_total=tokens_total,
                pairing_stats=pairing_stats,
            )
            logger.info("Copied %s -> %s (pairs=%s tokens=%s)", src.name, dst.name, pairs_total, tokens_total)
        except Exception as exc:
            failed_count += 1
            logger.warning("Failed processing file '%s': %s", src.name, exc)

    concat_failed = False
    if copied_files:
        try:
            concat_path = _write_concatenated_output(output_dir, copied_files)
            logger.info("Wrote concatenated output: %s", concat_path)
        except Exception as exc:
            concat_failed = True
            logger.warning("Failed writing concatenated output: %s", exc)

    logger.info(
        "Run complete. processed=%s failed=%s input_dir=%s output_dir=%s",
        len(copied_files),
        failed_count,
        input_dir,
        output_dir,
    )
    return 0 if (failed_count == 0 and not concat_failed) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy top-level tagged .txt chat files and append statistics.",
    )
    parser.add_argument("input_dir", help="Directory containing top-level .txt files")
    parser.add_argument("output_dir", help="Directory where copied files and stats are written")
    args = parser.parse_args()
    try:
        return run(args.input_dir, args.output_dir)
    except Exception as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

