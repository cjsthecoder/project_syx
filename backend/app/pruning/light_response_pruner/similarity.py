from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .normalize import normalize_for_prefix_match

_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_REQUIREMENT_ID_RE = re.compile(r"\b(?:FR|NFR)-\d+(?:\.\d+)*\b", re.IGNORECASE)
_FUNCTION_CALL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(")
_SNAKE_CASE_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]*\b")
_DOTTED_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")


@dataclass(frozen=True)
class SentenceSpan:
    start: int
    end: int
    text: str


def prune_similar_sentences(text: str, *, threshold: int = 94) -> str:
    if not text.strip():
        return text

    output_parts: list[str] = []
    prose_buffer: list[str] = []
    kept_normalized_sentences: list[str] = []
    in_code_block = False

    for line in text.splitlines(keepends=True):
        is_fence_line = line.strip().startswith("```")

        if in_code_block:
            output_parts.append(line)
            if is_fence_line:
                in_code_block = False
            continue

        if is_fence_line:
            pruned_prose = _prune_similar_prose(
                "".join(prose_buffer),
                kept_normalized_sentences,
                threshold,
            )
            if pruned_prose:
                output_parts.append(pruned_prose)
                if not pruned_prose.endswith("\n"):
                    output_parts.append("\n")
            prose_buffer = []
            in_code_block = True
            output_parts.append(line)
            continue

        prose_buffer.append(line)

    output_parts.append(
        _prune_similar_prose("".join(prose_buffer), kept_normalized_sentences, threshold)
    )
    return "".join(output_parts)


def _prune_similar_prose(
    text: str,
    kept_normalized_sentences: list[str],
    threshold: int,
) -> str:
    if not text:
        return ""

    sentence_spans = _sentence_spans(text)
    if not sentence_spans:
        return text

    output_parts: list[str] = []
    cursor = 0
    dropped_sentence = False

    for span in sentence_spans:
        output_parts.append(text[cursor : span.start])
        normalized_sentence = normalize_for_prefix_match(span.text)

        if (
            _is_protected_sentence(span.text)
            or not normalized_sentence
            or not _is_duplicate_sentence(normalized_sentence, kept_normalized_sentences, threshold)
        ):
            output_parts.append(text[span.start : span.end])
            if normalized_sentence and not _is_protected_sentence(span.text):
                kept_normalized_sentences.append(normalized_sentence)
        else:
            dropped_sentence = True

        cursor = span.end

    output_parts.append(text[cursor:])
    pruned_text = "".join(output_parts)
    if dropped_sentence:
        return pruned_text.rstrip()

    return pruned_text


def _sentence_spans(text: str) -> list[SentenceSpan]:
    spans: list[SentenceSpan] = []
    start = _first_non_whitespace_index(text)
    if start is None:
        return spans

    for match in _SENTENCE_END_RE.finditer(text):
        sentence_end = match.end()
        end = _consume_sentence_trailing_whitespace(text, sentence_end)
        sentence_text = text[start:sentence_end]
        if sentence_text.strip():
            spans.append(SentenceSpan(start=start, end=end, text=sentence_text))

        next_start = _first_non_whitespace_index(text[end:])
        if next_start is None:
            return spans
        start = end + next_start

    return spans


def _is_duplicate_sentence(
    normalized_sentence: str,
    kept_normalized_sentences: list[str],
    threshold: int,
) -> bool:
    for kept_sentence in kept_normalized_sentences:
        if fuzz.token_set_ratio(normalized_sentence, kept_sentence) >= threshold:
            return True

    return False


def _is_protected_sentence(sentence: str) -> bool:
    return (
        any(character.isdigit() for character in sentence)
        or _REQUIREMENT_ID_RE.search(sentence) is not None
        or _FUNCTION_CALL_RE.search(sentence) is not None
        or _SNAKE_CASE_RE.search(sentence) is not None
        or _DOTTED_IDENTIFIER_RE.search(sentence) is not None
    )


def _first_non_whitespace_index(text: str) -> int | None:
    for index, character in enumerate(text):
        if not character.isspace():
            return index

    return None


def _consume_sentence_trailing_whitespace(text: str, start: int) -> int:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor
