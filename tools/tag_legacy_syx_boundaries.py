#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

"""Add Syx memory boundary comments to legacy Daily/Sleep pair artifacts."""

import argparse
import logging
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.rag.syx_memory_artifact import (  # noqa: E402
    ensure_blank_line_before_begin_markers,
    ensure_entry_headings,
    generate_memory_id,
    normalize_legacy_artifact_wrappers,
    parse_syx_entries,
    snake_case_value,
)

logger = logging.getLogger("tag_legacy_syx_boundaries")

PAIR_RE = re.compile(
    r"(?P<block>=== BEGIN (?:DAILY|DREAM) PAIR ===\n.*?\n=== END (?:DAILY|DREAM) PAIR ===\n?)",
    re.DOTALL,
)
TIMESTAMP_RE = re.compile(r"^#timestamp:\s*(?P<timestamp>.+?)\s*$", re.MULTILINE)
BEGIN_BOUNDARY_RE = re.compile(r"<!-- begin syx:memory_id=mem_\d{8}_\d{6}_[0-9a-f]{4,8} -->")
END_BOUNDARY_RE = re.compile(r"<!-- end syx:memory_id=mem_\d{8}_\d{6}_[0-9a-f]{4,8} -->")
PAIR_DELIMITER_LINE_RE = re.compile(r"^=== (?:BEGIN|END) (?:DAILY|DREAM) PAIR ===\n?", re.MULTILINE)
DREAM_OUTPUT_TYPE_RE = re.compile(r"(?m)^dream_output_type:\s*(.+?)\s*$")


def _iter_paths(file_path: str | None, dir_path: str | None) -> Iterable[Path]:
    if file_path:
        yield Path(file_path)
    if dir_path:
        root = Path(dir_path)
        for suffix in ("*.txt", "*.md"):
            yield from root.rglob(suffix)


def _infer_project_id(path: Path) -> str:
    parts = path.resolve().parts
    for idx, part in enumerate(parts):
        if part == "memory" and idx + 1 < len(parts):
            return parts[idx + 1]
    return path.parent.name


def _infer_artifact_type(path: Path) -> str:
    lowered = [part.lower() for part in path.parts]
    if "dream" in lowered or path.name.lower().startswith("dream_"):
        return "dream_memory"
    if "sleep" in lowered or path.name.lower().startswith("sleep_"):
        return "sleep_memory"
    return "daily_memory"


def _already_wrapped(prefix: str, suffix: str) -> bool:
    return bool(BEGIN_BOUNDARY_RE.search(prefix[-160:]) and END_BOUNDARY_RE.search(suffix[:160]))


def _strip_pair_delimiters(block: str) -> str:
    return PAIR_DELIMITER_LINE_RE.sub("", block).strip() + "\n"


def _normalize_dream_output_types(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"dream_output_type: {snake_case_value(match.group(1))}"

    return DREAM_OUTPUT_TYPE_RE.sub(repl, text)


def tag_text(
    text: str,
    *,
    project_id: str,
    artifact_type: str = "daily_memory",
) -> Tuple[str, int, List[str]]:
    warnings: List[str] = []
    parsed = parse_syx_entries(text)
    warnings.extend(parsed.warnings)

    pieces: List[str] = []
    cursor = 0
    changed = 0
    for match in PAIR_RE.finditer(text):
        start, end = match.span("block")
        block = match.group("block")
        pieces.append(text[cursor:start])
        prefix = text[max(0, start - 200) : start]
        suffix = text[end : min(len(text), end + 200)]
        if _already_wrapped(prefix, suffix):
            stripped = _strip_pair_delimiters(block)
            pieces.append(stripped)
            if stripped != block:
                changed += 1
            cursor = end
            continue
        ts_match = TIMESTAMP_RE.search(block)
        if not ts_match:
            warnings.append(f"skipped pair without #timestamp at offset {start}")
            pieces.append(block)
            cursor = end
            continue
        timestamp = ts_match.group("timestamp").strip()
        memory_id = generate_memory_id(
            project_id=project_id,
            timestamp=timestamp,
            source="chat",
            entry_type="chat_pair",
            user_text=block,
            assistant_text="",
            route="legacy",
        )
        pieces.append(
            f"<!-- begin syx:memory_id={memory_id} -->\n"
            f"{_strip_pair_delimiters(block)}"
            f"<!-- end syx:memory_id={memory_id} -->\n"
        )
        changed += 1
        cursor = end
    pieces.append(text[cursor:])
    rendered = "".join(pieces)
    normalized = normalize_legacy_artifact_wrappers(
        rendered,
        artifact_type=artifact_type,
        project_id=project_id,
    )
    normalized = ensure_blank_line_before_begin_markers(normalized)
    normalized = _normalize_dream_output_types(normalized)
    normalized = ensure_entry_headings(normalized)
    if normalized != rendered:
        changed += 1
        rendered = normalized
    return rendered, changed, warnings


def process_path(path: Path, *, dry_run: bool, in_place: bool, backup: bool) -> int:
    text = path.read_text(encoding="utf-8", errors="ignore")
    project_id = _infer_project_id(path)
    artifact_type = _infer_artifact_type(path)
    new_text, changed, warnings = tag_text(text, project_id=project_id, artifact_type=artifact_type)
    for warning in warnings:
        logger.warning("%s: %s", path, warning)
    if changed == 0:
        logger.info("%s: no changes", path)
        return 0
    logger.info("%s: wrapped %s pair blocks", path, changed)
    if dry_run:
        return changed
    if not in_place:
        sys.stdout.write(new_text)
        return changed
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file")
    parser.add_argument("--dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.file and not args.dir:
        parser.error("provide --file or --dir")
    total = 0
    for path in _iter_paths(args.file, args.dir):
        if not path.is_file():
            logger.warning("skipping non-file path=%s", path)
            continue
        total += process_path(path, dry_run=args.dry_run, in_place=args.in_place, backup=args.backup)
    logger.info("wrapped total pair blocks=%s", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
