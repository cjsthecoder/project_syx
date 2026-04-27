#!/usr/bin/env python3
"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

Process top-level .txt chat logs and emit opening/closing boundary JSONL files.
"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any


logger = logging.getLogger("process_responses")

ASSISTANT_MARKER = "*** ASSISTANT (data-message-author-role: assistant) ***"
BOUNDARY_MARKERS = (
    "=== END",
    "=== TOPIC",
    "=== REFERENCES",
    "--- USER",
    "*** ASSISTANT",
)

FRONT_OUTPUT = "front.jsonl"
END_OUTPUT = "end.jsonl"

_SENTENCE_RE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", flags=re.DOTALL)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_WHITESPACE_RE = re.compile(r"\s+")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _validate_directory(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")


def _iter_txt_files(path: Path) -> list[Path]:
    # Per spec: process ".txt" only (lowercase), no recursion.
    return sorted([p for p in path.iterdir() if p.is_file() and p.suffix == ".txt"], key=lambda p: p.name)


def _normalize_text(text: str) -> str:
    normalized = (text or "").replace("’", "'").strip().lower()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    # Remove only trailing sentence punctuation, if present.
    return re.sub(r"[.!?]+\Z", "", normalized).strip()


def _split_sentences(text: str) -> list[str]:
    base = (text or "").strip()
    if not base:
        return []
    return [part.strip() for part in _SENTENCE_RE.findall(base) if part and part.strip()]


def _last_paragraph(text: str) -> str:
    base = (text or "").strip()
    if not base:
        return ""
    parts = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(base) if p and p.strip()]
    return parts[-1] if parts else ""


def _last_two_paragraphs(text: str) -> str:
    base = (text or "").strip()
    if not base:
        return ""
    parts = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(base) if p and p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "\n\n".join(parts[-2:])


def _fallback_front(source_file: str, chat_id: str) -> dict[str, str]:
    return {
        "source_file": source_file,
        "chat_id": chat_id,
        "first_sentence": "",
        "first_two_sentences": "",
        "normalized_first_sentence": "",
        "normalized_first_two_sentences": "",
    }


def _fallback_end(source_file: str, chat_id: str) -> dict[str, str]:
    return {
        "source_file": source_file,
        "chat_id": chat_id,
        "last_sentence": "",
        "last_two_sentences": "",
        "last_paragraph": "",
        "last_two_paragraphs": "",
        "normalized_last_sentence": "",
        "normalized_last_two_sentences": "",
        "normalized_last_paragraph": "",
        "normalized_last_two_paragraphs": "",
    }


def extract_front(response_text: str, source_file: str, chat_id: str) -> dict[str, str]:
    try:
        text = (response_text or "").strip()
        sentences = _split_sentences(text)
        first_sentence = sentences[0] if sentences else ""
        first_two_sentences = " ".join(sentences[:2]) if sentences else ""
        return {
            "source_file": source_file,
            "chat_id": chat_id,
            "first_sentence": first_sentence,
            "first_two_sentences": first_two_sentences,
            "normalized_first_sentence": _normalize_text(first_sentence),
            "normalized_first_two_sentences": _normalize_text(first_two_sentences),
        }
    except Exception as exc:
        logger.warning(
            "extract_front failed; source_file=%s chat_id=%s detail=%s",
            source_file,
            chat_id,
            exc,
        )
        return _fallback_front(source_file, chat_id)


def extract_end(response_text: str, source_file: str, chat_id: str) -> dict[str, str]:
    text = (response_text or "").strip()
    if not text:
        return _fallback_end(source_file, chat_id)

    try:
        sentences = _split_sentences(text)
    except Exception as exc:
        logger.warning(
            "sentence split failed; source_file=%s chat_id=%s detail=%s",
            source_file,
            chat_id,
            exc,
        )
        sentences = [text] if text else []

    try:
        last_paragraph = _last_paragraph(text)
        last_two_paragraphs = _last_two_paragraphs(text)
    except Exception as exc:
        logger.warning(
            "paragraph split failed; source_file=%s chat_id=%s detail=%s",
            source_file,
            chat_id,
            exc,
        )
        last_paragraph = text
        last_two_paragraphs = text

    try:
        if not sentences:
            last_sentence = ""
            last_two_sentences = ""
        elif len(sentences) == 1:
            last_sentence = sentences[0]
            last_two_sentences = sentences[0]
        else:
            last_sentence = sentences[-1]
            last_two_sentences = " ".join(sentences[-2:])

        return {
            "source_file": source_file,
            "chat_id": chat_id,
            "last_sentence": last_sentence,
            "last_two_sentences": last_two_sentences,
            "last_paragraph": last_paragraph,
            "last_two_paragraphs": last_two_paragraphs,
            "normalized_last_sentence": _normalize_text(last_sentence),
            "normalized_last_two_sentences": _normalize_text(last_two_sentences),
            "normalized_last_paragraph": _normalize_text(last_paragraph),
            "normalized_last_two_paragraphs": _normalize_text(last_two_paragraphs),
        }
    except Exception as exc:
        logger.warning(
            "extract_end failed; source_file=%s chat_id=%s detail=%s",
            source_file,
            chat_id,
            exc,
        )
        return _fallback_end(source_file, chat_id)


def _iter_assistant_blocks(text: str, source_file: str) -> list[str]:
    blocks: list[str] = []
    cursor = 0
    while True:
        start = text.find(ASSISTANT_MARKER, cursor)
        if start < 0:
            break
        body_start = start + len(ASSISTANT_MARKER)
        candidates = [text.find(marker, body_start) for marker in BOUNDARY_MARKERS]
        found = [idx for idx in candidates if idx >= 0]
        end = min(found) if found else -1
        if end < 0:
            logger.warning(
                "Malformed assistant block skipped (no boundary marker found); source_file=%s marker_index=%s",
                source_file,
                start,
            )
            cursor = body_start
            continue
        body = text[body_start:end].strip()
        blocks.append(body)
        cursor = end
    return blocks


def _write_jsonl_line(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(directory_path_raw: str) -> int:
    _setup_logging()
    directory_path = Path(directory_path_raw).resolve()
    _validate_directory(directory_path)

    txt_files = _iter_txt_files(directory_path)
    front_path = directory_path / FRONT_OUTPUT
    end_path = directory_path / END_OUTPUT

    chat_counter = 1
    files_failed = 0
    blocks_skipped = 0
    records_written = 0

    with open(front_path, "w", encoding="utf-8", newline="\n") as front_fh, open(
        end_path, "w", encoding="utf-8", newline="\n"
    ) as end_fh:
        for txt_file in txt_files:
            source_file = txt_file.name
            try:
                raw = txt_file.read_text(encoding="utf-8")
            except Exception as exc:
                files_failed += 1
                logger.warning("Failed reading file; source_file=%s detail=%s", source_file, exc)
                continue

            responses = _iter_assistant_blocks(raw, source_file)
            for response_text in responses:
                chat_id = str(chat_counter)
                chat_counter += 1
                try:
                    front_record = extract_front(response_text, source_file, chat_id)
                    end_record = extract_end(response_text, source_file, chat_id)
                    _write_jsonl_line(front_fh, front_record)
                    _write_jsonl_line(end_fh, end_record)
                    records_written += 1
                except Exception as exc:
                    # This should be rare because extract_* is already best-effort.
                    blocks_skipped += 1
                    logger.warning(
                        "Unexpected processing error; source_file=%s chat_id=%s detail=%s",
                        source_file,
                        chat_id,
                        exc,
                    )
                    continue

    logger.info(
        "Run complete. files=%s records=%s files_failed=%s blocks_skipped=%s front_output=%s end_output=%s",
        len(txt_files),
        records_written,
        files_failed,
        blocks_skipped,
        front_path,
        end_path,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process .txt chat logs and emit front.jsonl and end.jsonl boundary records.",
    )
    parser.add_argument("directory_path", help="Directory containing top-level .txt files to process")
    args = parser.parse_args()

    try:
        return run(args.directory_path)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
