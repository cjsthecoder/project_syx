"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Text span detection units for the light response pruner.

This module locates leading sentences and paragraph spans and detects structured
or fenced-code content used when trimming response text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextSpan:
    """A contiguous span of text located within a larger string.

    Attributes:
        start: Character offset where the span begins.
        end: Character offset just past the span's last character.
        text: Trimmed content for the ``[start, end)`` span.
    """

    start: int
    end: int
    text: str


def leading_sentence_span(text: str) -> TextSpan | None:
    """Return the span of the first sentence in ``text``, or None.

    A sentence ends at ``.``, ``!``, or ``?`` followed by whitespace or
    end-of-text. Returns None when there is no content or the text begins inside
    a fenced code block.

    Args:
        text: Text to scan from its first non-whitespace character.

    Returns:
        A TextSpan covering the leading sentence (including trailing
        whitespace in ``end``), or None.
    """
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
    """Split ``text`` into paragraph spans separated by blank lines.

    Each span's ``text`` is whitespace-trimmed, ``start`` points at the first
    non-whitespace character, and ``end`` marks the paragraph boundary. Empty
    paragraphs are skipped.

    Args:
        text: Text to split into paragraphs.

    Returns:
        Ordered list of paragraph TextSpans.
    """
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
    """Return True if ``text`` begins with markdown structure.

    Detects fenced code, headings, blockquotes, bullet lists, and ordered list
    markers so such content can be protected from end-trimming.

    Args:
        text: Paragraph text to inspect (leading whitespace is ignored).

    Returns:
        True if the text starts with a recognized structural marker.
    """
    stripped = text.lstrip()
    return (
        stripped.startswith("```")
        or stripped.startswith("#")
        or stripped.startswith(("- ", "* ", "+ ", "> "))
        or _starts_with_ordered_list_marker(stripped)
    )


def span_starts_inside_fenced_code_block(text: str, span: TextSpan) -> bool:
    """Return True if ``span`` begins inside a fenced code block of ``text``.

    Args:
        text: The full text containing the span.
        span: The span whose start position is tested.

    Returns:
        True if an odd number of code fences precede the span's start.
    """
    return _is_inside_fenced_code_block(text, span.start)


def _first_non_whitespace_index(text: str) -> int | None:
    """Return the index of the first non-whitespace character, or None if blank.

    Args:
        text: Text to scan.

    Returns:
        The zero-based index of the first non-whitespace character, or None when
        the text is empty or all whitespace.
    """
    for index, character in enumerate(text):
        if not character.isspace():
            return index

    return None


def _last_non_whitespace_end(text: str, start: int, end: int) -> int:
    """Return the exclusive end index after trailing whitespace in a slice.

    Args:
        text: Text being scanned.
        start: Lower bound (inclusive) below which scanning stops.
        end: Exclusive end of the slice to trim back from.

    Returns:
        The index just past the last non-whitespace character within
        ``[start, end)``.
    """
    cursor = end
    while cursor > start and text[cursor - 1].isspace():
        cursor -= 1

    return cursor


def _consume_following_whitespace(text: str, start: int) -> int:
    """Return the index of the first non-whitespace character at or after ``start``.

    Args:
        text: Text being scanned.
        start: Index to begin scanning from.

    Returns:
        The index of the next non-whitespace character, or ``len(text)`` if none
        remain.
    """
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor


def _next_blank_line_index(text: str, start: int) -> int | None:
    """Find the newline that precedes the next blank line at or after ``start``.

    Args:
        text: Text being scanned.
        start: Index to begin scanning from.

    Returns:
        The index of the newline immediately before the next blank line, or None
        when no blank-line separator remains.
    """
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
    """Skip the whitespace making up a blank-line separator.

    Args:
        text: Text being scanned.
        start: Index of the separator's leading newline.

    Returns:
        The index of the first character of the next paragraph.
    """
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor


def _is_inside_fenced_code_block(text: str, index: int) -> bool:
    """Return True if ``index`` falls inside an open fenced code block.

    Args:
        text: Text being scanned.
        index: Position whose enclosure is tested.

    Returns:
        True when an odd number of code fences appear before ``index``.
    """
    in_fence = False

    for line in text[:index].splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence

    return in_fence


def _starts_with_ordered_list_marker(text: str) -> bool:
    """Return True if ``text`` begins with an ordered list marker (e.g. "1.").

    Args:
        text: Text to inspect, expected to be left-stripped.

    Returns:
        True when one or more leading digits are immediately followed by a dot.
    """
    number = ""
    for character in text:
        if character.isdigit():
            number += character
            continue

        return bool(number) and character == "."

    return False
