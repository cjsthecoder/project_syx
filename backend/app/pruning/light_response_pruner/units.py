"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
from __future__ import annotations

"""
Text span detection units for the light response pruner.

This module locates leading sentences and paragraph spans and detects structured
or fenced-code content used when trimming response text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int
    text: str


def leading_sentence_span(text: str) -> TextSpan | None:
    start = _first_non_whitespace_index(text)
    if start is None or _is_inside_fenced_code_block(text, start):
        return None

    for index in range(start, len(text)):
        if text[index] not in ".!?":
            continue

        next_index = index + 1
        if next_index < len(text) and not text[next_index].isspace():
            continue

        end = _consume_following_whitespace(text, next_index)
        return TextSpan(start=start, end=end, text=text[start : index + 1])

    return None


def paragraph_spans(text: str) -> list[TextSpan]:
    spans: list[TextSpan] = []
    cursor = 0

    while cursor < len(text):
        paragraph_start = cursor
        separator_start = _next_blank_line_index(text, cursor)

        if separator_start is None:
            paragraph_end = len(text)
            cursor = len(text)
        else:
            paragraph_end = separator_start
            cursor = _consume_blank_line_separator(text, separator_start)

        stripped_start = _first_non_whitespace_index(text[paragraph_start:paragraph_end])
        if stripped_start is None:
            continue

        start = paragraph_start + stripped_start
        stripped_end = _last_non_whitespace_end(text, start, paragraph_end)
        spans.append(TextSpan(start=start, end=paragraph_end, text=text[start:stripped_end]))

    return spans


def starts_with_structured_content(text: str) -> bool:
    stripped = text.lstrip()
    return (
        stripped.startswith("```")
        or stripped.startswith("#")
        or stripped.startswith(("- ", "* ", "+ ", "> "))
        or _starts_with_ordered_list_marker(stripped)
    )


def span_starts_inside_fenced_code_block(text: str, span: TextSpan) -> bool:
    return _is_inside_fenced_code_block(text, span.start)


def _first_non_whitespace_index(text: str) -> int | None:
    for index, character in enumerate(text):
        if not character.isspace():
            return index

    return None


def _last_non_whitespace_end(text: str, start: int, end: int) -> int:
    cursor = end
    while cursor > start and text[cursor - 1].isspace():
        cursor -= 1

    return cursor


def _consume_following_whitespace(text: str, start: int) -> int:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor


def _next_blank_line_index(text: str, start: int) -> int | None:
    cursor = start
    while cursor < len(text):
        newline_index = text.find("\n", cursor)
        if newline_index == -1:
            return None

        next_line_start = newline_index + 1
        next_line_end = text.find("\n", next_line_start)
        if next_line_end == -1:
            next_line_end = len(text)

        if text[next_line_start:next_line_end].strip() == "":
            return newline_index

        cursor = next_line_start

    return None


def _consume_blank_line_separator(text: str, start: int) -> int:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor


def _is_inside_fenced_code_block(text: str, index: int) -> bool:
    in_fence = False

    for line in text[:index].splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence

    return in_fence


def _starts_with_ordered_list_marker(text: str) -> bool:
    number = ""
    for character in text:
        if character.isdigit():
            number += character
            continue

        return bool(number) and character == "."

    return False
