"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Near-duplicate sentence pruning for the light response pruner.

Detects and removes sentences that are fuzzily similar to ones already kept,
while protecting code blocks and sentences containing identifiers or numbers.
"""

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
    """A sentence located within the source text.

    Attributes:
        start: Character offset where the sentence begins.
        end: Character offset just past the sentence's last character.
        text: Raw sentence text for the ``[start, end)`` span.
    """

    start: int
    end: int
    text: str


def prune_similar_sentences(text: str, *, threshold: int = 94) -> str:
    """Remove sentences that are near-duplicates of earlier kept sentences.

    Similarity is measured with a fuzzy token-set ratio against previously kept
    sentences. Fenced code blocks and sentences containing digits, requirement
    ids, or code-like identifiers are protected from removal.

    Args:
        text: Prose (possibly containing code blocks) to deduplicate.
        threshold: Minimum similarity score (0-100) to treat as a duplicate.

    Returns:
        Text with near-duplicate sentences removed.
    """
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
    """Drop near-duplicate sentences from a prose segment.

    Each non-protected, non-empty sentence is compared against the running list
    of kept sentences; survivors are appended to ``kept_normalized_sentences``
    so subsequent segments dedupe against them too. The list is mutated in place.

    Args:
        text: Prose segment (no fenced code) to deduplicate.
        kept_normalized_sentences: Normalized sentences kept so far; updated in
            place with newly kept sentences.
        threshold: Minimum fuzzy similarity score (0-100) to treat as duplicate.

    Returns:
        The prose with near-duplicate sentences removed.
    """
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
    """Split ``text`` into sentence spans on terminal punctuation.

    Sentences end at ``.``, ``!``, or ``?`` followed by whitespace or
    end-of-text; each span's ``end`` includes trailing whitespace.

    Args:
        text: Prose text to split.

    Returns:
        Ordered list of non-empty sentence spans.
    """
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
    """Return True if a sentence fuzzily matches any already-kept sentence.

    Args:
        normalized_sentence: Normalized candidate sentence.
        kept_normalized_sentences: Normalized sentences already retained.
        threshold: Minimum token-set ratio (0-100) to count as a duplicate.

    Returns:
        True when at least one kept sentence scores at or above ``threshold``.
    """
    for kept_sentence in kept_normalized_sentences:
        if fuzz.token_set_ratio(normalized_sentence, kept_sentence) >= threshold:
            return True

    return False


def _is_protected_sentence(sentence: str) -> bool:
    """Return True if a sentence must never be pruned as a duplicate.

    Protects sentences that carry data-bearing content (digits, requirement
    ids, function calls, snake_case, or dotted identifiers) where fuzzy matching
    could discard meaningful distinctions.

    Args:
        sentence: Raw (un-normalized) sentence text.

    Returns:
        True when the sentence contains protected content.
    """
    return (
        any(character.isdigit() for character in sentence)
        or _REQUIREMENT_ID_RE.search(sentence) is not None
        or _FUNCTION_CALL_RE.search(sentence) is not None
        or _SNAKE_CASE_RE.search(sentence) is not None
        or _DOTTED_IDENTIFIER_RE.search(sentence) is not None
    )


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


def _consume_sentence_trailing_whitespace(text: str, start: int) -> int:
    """Return the index past trailing whitespace following a sentence.

    Args:
        text: Text being scanned.
        start: Index immediately after the sentence's terminal punctuation.

    Returns:
        The index of the next non-whitespace character, or ``len(text)`` if none
        remain.
    """
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1

    return cursor
