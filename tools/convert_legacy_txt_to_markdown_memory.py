#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

Convert legacy Syx `.txt` memory artifacts into modern markdown memory artifacts.
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.rag.syx_memory_artifact import (  # noqa: E402
    generate_memory_id,
    render_artifact_header,
    render_memory_entry,
    topics_to_list,
)


logger = logging.getLogger("convert_legacy_txt_to_markdown_memory")

PAIR_RE = re.compile(
    r"(?P<block>=== BEGIN (?:DAILY|DREAM) PAIR ===\n.*?\n=== END (?:DAILY|DREAM) PAIR ===\n?)",
    re.DOTALL,
)
LEGACY_MEMORY_WRAPPER_RE = re.compile(
    r"^=== (?:BEGIN|END) (?P<kind>DAILY|DREAM) MEMORY:\s*(?P<date>\d{2}/\d{2}/\d{4}) ===\s*$",
    re.MULTILINE,
)
LEGACY_METADATA_RE = re.compile(r"^#(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<value>.*?)\s*$", re.MULTILINE)
USER_MARKER_RE = re.compile(r"^--- USER \(data-message-author-role:\s*user\) ---\s*$", re.MULTILINE)
ASSISTANT_MARKER_RE = re.compile(r"^\*\*\* ASSISTANT \(data-message-author-role:\s*assistant\) \*\*\*\s*$", re.MULTILINE)
PAIR_DELIMITER_RE = re.compile(r"^=== (?:BEGIN|END) (?:DAILY|DREAM) PAIR ===\s*$", re.MULTILINE)
TOPIC_HEADER_RE = re.compile(r"^=== TOPIC:\s*(?P<topic>.*?)\s*===\s*$", re.MULTILINE)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _normalize_lf(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _infer_project_id(path: Path) -> str:
    parts = path.resolve().parts
    for idx, part in enumerate(parts):
        if part == "memory" and idx + 1 < len(parts):
            return parts[idx + 1]
    return path.parent.name


def _infer_artifact_type(path: Path) -> str:
    lowered = [part.lower() for part in path.parts]
    name = path.name.lower()
    if "dream" in lowered or name.startswith("dream_"):
        return "dream_memory"
    if "sleep" in lowered or name.startswith("sleep_"):
        return "sleep_memory"
    return "daily_memory"


def _infer_scopes(path: Path, artifact_type: str) -> tuple[str, str]:
    lowered = [part.lower() for part in path.parts]
    if artifact_type == "sleep_memory" or "uploads" in lowered:
        return "daily", "ltm"
    if artifact_type == "dream_memory":
        return "dream", "dream"
    return "daily", "daily"


def _infer_memory_date(text: str, path: Path) -> str:
    match = LEGACY_MEMORY_WRAPPER_RE.search(text)
    if match:
        raw = match.group("date").strip()
        try:
            return datetime.strptime(raw, "%m/%d/%Y").strftime("%m-%d-%Y")
        except ValueError:
            return raw.replace("/", "-")
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d-%Y")
    except OSError:
        return datetime.now().strftime("%m-%d-%Y")


def _compact_metadata_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_bool(value: Any, default: bool = False) -> bool:
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _metadata_lines(block: str) -> dict[str, str]:
    return {m.group("key").strip(): m.group("value").strip() for m in LEGACY_METADATA_RE.finditer(block)}


def _strip_legacy_metadata_lines(block: str) -> str:
    return LEGACY_METADATA_RE.sub("", block)


def _extract_pair_body(block: str) -> tuple[Optional[str], Optional[str]]:
    without_delimiters = PAIR_DELIMITER_RE.sub("", _normalize_lf(block)).strip()
    without_metadata = _strip_legacy_metadata_lines(without_delimiters).strip()
    user_match = USER_MARKER_RE.search(without_metadata)
    assistant_match = ASSISTANT_MARKER_RE.search(without_metadata)
    if not user_match or not assistant_match or user_match.end() > assistant_match.start():
        return None, None
    user_text = without_metadata[user_match.end() : assistant_match.start()].strip()
    assistant_text = without_metadata[assistant_match.end() :].strip()
    return user_text, assistant_text


def _fallback_timestamp(memory_date: str, sequence: int) -> str:
    try:
        dt = datetime.strptime(memory_date, "%m-%d-%Y") + timedelta(seconds=max(0, sequence - 1))
    except ValueError:
        dt = datetime.now().replace(microsecond=0) + timedelta(seconds=max(0, sequence - 1))
    return dt.strftime("%m-%d-%Y_%H:%M:%S")


def _base_metadata(
    *,
    memory_id: str,
    entry_type: str,
    source: str,
    source_agent: str,
    source_scope: str,
    current_scope: str,
    timestamp: str,
    route: str,
    keep: bool,
    source_file: str,
    sequence: int,
) -> dict[str, Any]:
    return {
        "memory_id": memory_id,
        "entry_type": entry_type,
        "source": source,
        "source_agent": source_agent,
        "source_scope": source_scope,
        "current_scope": current_scope,
        "timestamp": timestamp,
        "route": route,
        "keep": bool(keep),
        "day_sequence": int(sequence),
        "source_file": source_file,
    }


def _pair_metadata(
    *,
    block: str,
    memory_id: str,
    source_file: str,
    source_scope: str,
    current_scope: str,
    timestamp: str,
    sequence: int,
    topics_to_list_fn: Any,
) -> dict[str, Any]:
    legacy = _metadata_lines(block)
    route = _compact_metadata_value(legacy.get("route")) or "legacy"
    metadata = _base_metadata(
        memory_id=memory_id,
        entry_type="chat_pair",
        source="chat",
        source_agent="syx",
        source_scope=source_scope,
        current_scope=current_scope,
        timestamp=timestamp,
        route=route,
        keep=_parse_bool(legacy.get("keep"), default=False),
        source_file=source_file,
        sequence=sequence,
    )
    topics = topics_to_list_fn(legacy.get("topics"))
    if topics:
        metadata["topics"] = topics
    intent = _compact_metadata_value(legacy.get("intent"))
    if intent:
        metadata["intent"] = intent
    tag_type = _compact_metadata_value(legacy.get("type"))
    if tag_type:
        metadata["type"] = tag_type
    semantic_handle = _compact_metadata_value(legacy.get("semantic_handle"))
    if semantic_handle:
        metadata["semantic_handle"] = semantic_handle
    return metadata


def _residual_text(text: str, occupied: list[tuple[int, int]]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(occupied):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    residual = "".join(pieces)
    residual = LEGACY_MEMORY_WRAPPER_RE.sub("", residual)
    residual = TOPIC_HEADER_RE.sub("", residual)
    residual = LEGACY_METADATA_RE.sub("", residual)
    return residual.strip()


def _render_residual_entry(
    *,
    residual: str,
    project_id: str,
    source_file: str,
    source_scope: str,
    current_scope: str,
    memory_date: str,
    sequence: int,
) -> str:
    timestamp = _fallback_timestamp(memory_date, sequence)
    memory_id = generate_memory_id(
        project_id=project_id,
        timestamp=timestamp,
        source="legacy_import",
        entry_type="note",
        user_text=residual,
        assistant_text="",
        route="legacy",
    )
    metadata = _base_metadata(
        memory_id=memory_id,
        entry_type="note",
        source="legacy_import",
        source_agent="syx",
        source_scope=source_scope,
        current_scope=current_scope,
        timestamp=timestamp,
        route="legacy",
        keep=False,
        source_file=source_file,
        sequence=sequence,
    )
    metadata["type"] = "unparsed_legacy_section"
    return render_memory_entry(memory_id=memory_id, metadata=metadata, body_text=residual)


def convert_text(
    text: str,
    *,
    path: Path,
    project_id: str,
    artifact_type: str,
) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_lf(text)
    memory_date = _infer_memory_date(normalized, path)
    source_scope, current_scope = _infer_scopes(path, artifact_type)
    blocks: list[str] = [
        render_artifact_header(
            artifact_type=artifact_type,
            project_id=project_id,
            memory_date=memory_date,
        )
    ]
    occupied: list[tuple[int, int]] = []
    converted_pairs = 0
    fallback_pairs = 0
    memory_ids: list[str] = []

    for sequence, match in enumerate(PAIR_RE.finditer(normalized), start=1):
        block = match.group("block")
        occupied.append(match.span("block"))
        legacy = _metadata_lines(block)
        timestamp = _compact_metadata_value(legacy.get("timestamp")) or _fallback_timestamp(memory_date, sequence)
        route = _compact_metadata_value(legacy.get("route")) or "legacy"
        semantic_handle = _compact_metadata_value(legacy.get("semantic_handle"))
        user_text, assistant_text = _extract_pair_body(block)
        if user_text is not None and assistant_text is not None:
            memory_id = generate_memory_id(
                project_id=project_id,
                timestamp=timestamp,
                source="chat",
                entry_type="chat_pair",
                user_text=user_text,
                assistant_text=assistant_text,
                route=route,
                semantic_handle=semantic_handle,
            )
            metadata = _pair_metadata(
                block=block,
                memory_id=memory_id,
                source_file=path.name,
                source_scope=source_scope,
                current_scope=current_scope,
                timestamp=timestamp,
                sequence=sequence,
                topics_to_list_fn=topics_to_list,
            )
            rendered = render_memory_entry(
                memory_id=memory_id,
                metadata=metadata,
                user_text=user_text,
                assistant_text=assistant_text,
            )
            converted_pairs += 1
        else:
            memory_id = generate_memory_id(
                project_id=project_id,
                timestamp=timestamp,
                source="legacy_import",
                entry_type="note",
                user_text=block,
                assistant_text="",
                route=route,
            )
            metadata = _base_metadata(
                memory_id=memory_id,
                entry_type="note",
                source="legacy_import",
                source_agent="syx",
                source_scope=source_scope,
                current_scope=current_scope,
                timestamp=timestamp,
                route=route,
                keep=_parse_bool(legacy.get("keep"), default=False),
                source_file=path.name,
                sequence=sequence,
            )
            metadata["type"] = "unparsed_legacy_pair"
            rendered = render_memory_entry(memory_id=memory_id, metadata=metadata, body_text=block.strip())
            fallback_pairs += 1
        memory_ids.append(memory_id)
        blocks.append(rendered)

    residual = _residual_text(normalized, occupied)
    residual_entries = 0
    if residual:
        residual_entries = 1
        rendered = _render_residual_entry(
            residual=residual,
            project_id=project_id,
            source_file=path.name,
            source_scope=source_scope,
            current_scope=current_scope,
            memory_date=memory_date,
            sequence=len(memory_ids) + 1,
        )
        blocks.append(rendered)

    output = "".join(blocks).rstrip() + "\n"
    stats = {
        "input_file": str(path),
        "project_id": project_id,
        "artifact_type": artifact_type,
        "memory_date": memory_date,
        "source_scope": source_scope,
        "current_scope": current_scope,
        "converted_pairs": int(converted_pairs),
        "fallback_pairs": int(fallback_pairs),
        "residual_entries": int(residual_entries),
        "memory_ids": memory_ids,
    }
    return output, stats


def _iter_input_files(file_path: Optional[str], dir_path: Optional[str], recursive: bool) -> Iterable[Path]:
    if file_path:
        yield Path(file_path).resolve()
    if dir_path:
        root = Path(dir_path).resolve()
        pattern = "**/*.txt" if recursive else "*.txt"
        yield from sorted(root.glob(pattern), key=lambda p: str(p).lower())


def _destination_path(input_path: Path, output_dir: Path) -> Path:
    candidate = output_dir / f"{input_path.stem}.md"
    if not candidate.exists():
        return candidate
    idx = 1
    while True:
        candidate = output_dir / f"{input_path.stem}_{idx}.md"
        if not candidate.exists():
            return candidate
        idx += 1


def process_path(path: Path, *, output_dir: Path, project_id: Optional[str], dry_run: bool) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")
    if path.suffix.lower() != ".txt":
        raise ValueError(f"Input path must be a .txt file: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    resolved_project_id = project_id or _infer_project_id(path)
    artifact_type = _infer_artifact_type(path)
    rendered, stats = convert_text(
        text,
        path=path,
        project_id=resolved_project_id,
        artifact_type=artifact_type,
    )
    out_path = _destination_path(path, output_dir)
    stats["output_file"] = str(out_path)
    if not dry_run:
        out_path.write_text(rendered, encoding="utf-8", newline="\n")
    return stats


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Convert legacy Syx .txt memory artifacts into modern .md memory artifacts."
    )
    parser.add_argument("--file", help="One legacy .txt memory artifact to convert")
    parser.add_argument("--dir", help="Directory of legacy .txt memory artifacts to convert")
    parser.add_argument("--output-dir", required=True, help="Directory where converted .md files are written")
    parser.add_argument("--project-id", default=None, help="Override project_id; defaults to inference from path")
    parser.add_argument("--recursive", action="store_true", help="Recurse when --dir is provided")
    parser.add_argument("--dry-run", action="store_true", help="Report conversion stats without writing .md files")
    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("provide --file or --dir")

    output_dir = Path(args.output_dir).resolve()
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    elif not output_dir.exists():
        logger.info("dry-run: output directory does not exist yet: %s", output_dir)

    stats_rows: list[dict[str, Any]] = []
    failed = 0
    for path in _iter_input_files(args.file, args.dir, bool(args.recursive)):
        try:
            stats = process_path(path, output_dir=output_dir, project_id=args.project_id, dry_run=bool(args.dry_run))
            stats_rows.append(stats)
            logger.info(
                "%s -> %s converted_pairs=%s fallback_pairs=%s residual_entries=%s",
                path,
                stats.get("output_file"),
                stats.get("converted_pairs"),
                stats.get("fallback_pairs"),
                stats.get("residual_entries"),
            )
        except Exception as exc:
            failed += 1
            logger.warning("failed converting path=%s detail=%s", path, exc)

    if stats_rows and not args.dry_run:
        stats_path = output_dir / "conversion_statistics.jsonl"
        with open(stats_path, "a", encoding="utf-8", newline="\n") as sf:
            for row in stats_rows:
                payload = {"ts": datetime.now().isoformat(), **row}
                sf.write(json.dumps(payload, ensure_ascii=False) + "\n")
        logger.info("wrote conversion statistics: %s", stats_path)

    logger.info("run complete converted=%s failed=%s", len(stats_rows), failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
