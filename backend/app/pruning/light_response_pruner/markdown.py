"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

import re

_ATX_HEADING_RE = re.compile(r"^(?P<indent>\s*)#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^(?P<indent>\s*)>\s?", re.MULTILINE)
_BULLET_RE = re.compile(r"^(?P<indent>\s*)[-*+]\s+", re.MULTILINE)
_DOT_BULLET_RE = re.compile(r"^(?P<indent>\s*)\.\s+", re.MULTILINE)
_ORDERED_LIST_RE = re.compile(r"^(?P<indent>\s*)\d+[.)]\s+", re.MULTILINE)
_HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_STRONG_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EMPHASIS_RE = re.compile(r"(?<!\*)\*(?!\*)(?=\S)(.+?)(?<=\S)(?<!\*)\*(?!\*)")
_UNDERSCORE_EMPHASIS_RE = re.compile(
    r"(?<![\w_])_(?!_)(?=\S)(.+?)(?<=\S)(?<!_)_(?![\w_])"
)
_STRIKETHROUGH_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_REQUIREMENT_NUMBERED_LINE_RE = re.compile(
    r"^\s*\d+[.)]\s*(?:"
    r"(?:Q|A)\s*[:\-]|"
    r"(?:FR|NFR)\s*[-.]|"
    r"(?:requirement|req|question|answer)\b"
    r")",
    re.IGNORECASE,
)


def strip_markdown_markup(text: str) -> str:
    segments: list[str] = []
    prose_lines: list[str] = []
    in_code_block = False

    for line in text.splitlines(keepends=True):
        if in_code_block:
            segments.append(line)
            if line.strip().startswith("```"):
                in_code_block = False
            continue

        if line.strip().startswith("```"):
            prose = _strip_markdown_prose("".join(prose_lines))
            if prose:
                segments.append(prose)
            prose_lines = []
            in_code_block = True
            segments.append(line)
            continue

        prose_lines.append(line)

    prose = _strip_markdown_prose("".join(prose_lines))
    if prose:
        segments.append(prose)

    return "".join(segments)


def _strip_markdown_prose(text: str) -> str:
    stripped = _HORIZONTAL_RULE_RE.sub("", text)
    stripped = _ATX_HEADING_RE.sub(lambda match: match.group("indent"), stripped)
    stripped = _BLOCKQUOTE_RE.sub(lambda match: match.group("indent"), stripped)
    stripped = _strip_line_markers_with_protection(stripped)
    stripped = _IMAGE_RE.sub(r"\1", stripped)
    stripped = _LINK_RE.sub(r"\1", stripped)
    stripped = _INLINE_CODE_RE.sub(r"\1", stripped)
    stripped = _STRONG_RE.sub(r"\2", stripped)
    stripped = _STRIKETHROUGH_RE.sub(r"\1", stripped)
    stripped = _EMPHASIS_RE.sub(r"\1", stripped)
    return _UNDERSCORE_EMPHASIS_RE.sub(r"\1", stripped)


def _strip_line_markers_with_protection(text: str) -> str:
    lines = text.splitlines(keepends=True)
    processed_lines: list[str] = []

    for line in lines:
        if _REQUIREMENT_NUMBERED_LINE_RE.match(line):
            processed_lines.append(line)
            continue

        line = _BULLET_RE.sub(lambda match: match.group("indent"), line)
        line = _DOT_BULLET_RE.sub(lambda match: match.group("indent"), line)
        line = _ORDERED_LIST_RE.sub(lambda match: match.group("indent"), line)
        processed_lines.append(line)

    return "".join(processed_lines)
