"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
from __future__ import annotations

"""
Core pruning engine for the light response pruner.

Provides the Pruner class and PrunerConfig that orchestrate markdown stripping,
front/end prefix trimming, whitespace compaction, and similarity pruning to
produce a structured PruneResult.
"""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import load_rules
from .exceptions import PrunerConfigError, PrunerInputError
from .markdown import strip_markdown_markup
from .models import PruneResult, PruneRules, WhitespaceMode
from .normalize import normalize_for_prefix_match
from .similarity import prune_similar_sentences
from .units import (
    leading_sentence_span,
    paragraph_spans,
    span_starts_inside_fenced_code_block,
    starts_with_structured_content,
)
from .whitespace import compact_whitespace

RuleSource = PruneRules | Mapping[str, Any] | str | Path
RuleSources = RuleSource | Sequence[RuleSource]
logger = logging.getLogger(__name__)


class PrunerConfig:
    def __init__(
        self,
        *,
        max_response_size: int = 50_000,
        max_front_units: int = 3,
        similarity_threshold: int = 90,
        whitespace_mode: WhitespaceMode = "compact_prose",
        response_pruning: Mapping[str, bool] | None = None,
    ) -> None:
        if not isinstance(max_response_size, int):
            raise PrunerConfigError("max_response_size must be an int")
        if max_response_size <= 0:
            raise PrunerConfigError("max_response_size must be greater than 0")
        if not isinstance(max_front_units, int):
            raise PrunerConfigError("max_front_units must be an int")
        if max_front_units <= 0:
            raise PrunerConfigError("max_front_units must be greater than 0")
        if not isinstance(similarity_threshold, int):
            raise PrunerConfigError("similarity_threshold must be an int")
        if not 0 <= similarity_threshold <= 100:
            raise PrunerConfigError("similarity_threshold must be between 0 and 100")
        if whitespace_mode not in {"off", "compact_prose", "preserve_code"}:
            raise PrunerConfigError(
                "whitespace_mode must be one of: off, compact_prose, preserve_code"
            )

        default_response_pruning = {
            "enabled": True,
            "front_enabled": True,
            "end_enabled": True,
            "markdown_enabled": True,
            "whitespace_enabled": True,
            "similarity_enabled": True,
        }
        if response_pruning is None:
            normalized_response_pruning = default_response_pruning
        else:
            normalized_response_pruning = _normalize_response_pruning_config(
                response_pruning, defaults=default_response_pruning
            )

        self.max_response_size = max_response_size
        self.max_front_units = max_front_units
        self.similarity_threshold = similarity_threshold
        self.whitespace_mode = whitespace_mode
        self.response_pruning = normalized_response_pruning


class Pruner:
    def __init__(self, *, rules: PruneRules, config: PrunerConfig | None = None) -> None:
        self.rules = rules
        self.config = config or PrunerConfig()
        self._front_prefixes = _normalized_front_prefixes(rules)
        self._end_prefixes = _normalized_end_prefixes(rules)

    @classmethod
    def from_rules(
        cls,
        rules: RuleSources,
        *,
        config: PrunerConfig | None = None,
        strip_comment_keys: bool = False,
    ) -> "Pruner":
        loaded_rules = load_rules(rules, strip_comment_keys=strip_comment_keys)
        return cls(rules=loaded_rules, config=config)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        config: PrunerConfig | None = None,
        strip_comment_keys: bool = True,
    ) -> "Pruner":
        return cls.from_rules(path, config=config, strip_comment_keys=strip_comment_keys)

    @classmethod
    def from_files(
        cls,
        paths: Sequence[str | Path],
        *,
        config: PrunerConfig | None = None,
        strip_comment_keys: bool = True,
    ) -> "Pruner":
        return cls.from_rules(list(paths), config=config, strip_comment_keys=strip_comment_keys)

    def prune(self, text: str) -> PruneResult:
        if not isinstance(text, str):
            raise PrunerInputError("text must be a string")

        if len(text) > self.config.max_response_size:
            logger.warning(
                "response exceeds configured max_response_size; length=%s max=%s",
                len(text),
                self.config.max_response_size,
            )
            raise PrunerInputError(
                f"response length {len(text)} exceeds configured max_response_size "
                f"{self.config.max_response_size}"
            )

        working_text = text
        markdown_changed = False
        if (
            self.config.response_pruning["enabled"]
            and self.config.response_pruning["markdown_enabled"]
        ):
            working_text = strip_markdown_markup(text)
            markdown_changed = working_text != text
        front_offset = 0
        matched_front_prefixes: list[str] = []
        matched_end_prefixes: list[str] = []
        front_units_removed = 0
        blocked_by_safety = False

        if (
            self.config.response_pruning["enabled"]
            and self.config.response_pruning["front_enabled"]
            and self.rules.front is not None
        ):
            front_result = self._prune_front(working_text)
            working_text = front_result.text
            front_offset = front_result.offset
            matched_front_prefixes = front_result.matched_prefixes
            front_units_removed = front_result.units_removed
            blocked_by_safety = blocked_by_safety or front_result.blocked_by_safety

        end_span_removed: tuple[int, int] | None = None
        if (
            self.config.response_pruning["enabled"]
            and self.config.response_pruning["end_enabled"]
            and self.rules.end is not None
        ):
            end_result = self._prune_end(working_text, original_offset=front_offset)
            working_text = end_result.text
            matched_end_prefixes = end_result.matched_prefixes
            end_span_removed = end_result.span_removed
            blocked_by_safety = blocked_by_safety or end_result.blocked_by_safety

        whitespace_changed = False
        if (
            self.config.response_pruning["enabled"]
            and self.config.response_pruning["whitespace_enabled"]
            and self.config.whitespace_mode in {"compact_prose", "preserve_code"}
        ):
            before_whitespace = working_text
            working_text = compact_whitespace(working_text)
            whitespace_changed = working_text != before_whitespace

        similarity_changed = False
        if (
            self.config.response_pruning["enabled"]
            and self.config.response_pruning["similarity_enabled"]
        ):
            before_similarity = working_text
            working_text = prune_similar_sentences(
                working_text,
                threshold=self.config.similarity_threshold,
            )
            similarity_changed = working_text != before_similarity

        trimmed_front = front_units_removed > 0
        trimmed_end = end_span_removed is not None

        return PruneResult(
            original_text=text,
            pruned_text=working_text,
            changed=(
                markdown_changed
                or trimmed_front
                or trimmed_end
                or whitespace_changed
                or similarity_changed
            ),
            trimmed_front=trimmed_front,
            trimmed_end=trimmed_end,
            matched_front_prefixes=matched_front_prefixes,
            matched_end_prefixes=matched_end_prefixes,
            front_units_removed=front_units_removed,
            end_span_removed=end_span_removed,
            blocked_by_safety=blocked_by_safety,
        )

    def _prune_front(self, text: str) -> "_FrontPruneState":
        working_text = text
        original_offset = 0
        matched_prefixes: list[str] = []
        units_removed = 0
        blocked_by_safety = False

        while units_removed < self.config.max_front_units:
            span = leading_sentence_span(working_text)
            if span is None:
                break

            matched_prefix = _matching_prefix(span.text, self._front_prefixes)
            if matched_prefix is None:
                break

            next_text = working_text[span.end :]
            if not next_text.strip():
                blocked_by_safety = True
                break

            matched_prefixes.append(matched_prefix)
            original_offset += span.end
            working_text = next_text
            units_removed += 1

        return _FrontPruneState(
            text=working_text,
            offset=original_offset,
            matched_prefixes=matched_prefixes,
            units_removed=units_removed,
            blocked_by_safety=blocked_by_safety,
        )

    def _prune_end(self, text: str, *, original_offset: int) -> "_EndPruneState":
        candidate_spans = paragraph_spans(text)[-2:]
        for span in candidate_spans:
            if span_starts_inside_fenced_code_block(text, span):
                continue

            if starts_with_structured_content(span.text):
                continue

            matched_prefix = _matching_prefix(span.text, self._end_prefixes)
            if matched_prefix is None:
                continue

            next_text = text[: span.start].rstrip()
            if not next_text.strip():
                return _EndPruneState(
                    text=text,
                    matched_prefixes=[],
                    span_removed=None,
                    blocked_by_safety=True,
                )

            return _EndPruneState(
                text=next_text,
                matched_prefixes=[matched_prefix],
                span_removed=(original_offset + span.start, original_offset + len(text)),
                blocked_by_safety=False,
            )

        return _EndPruneState(
            text=text,
            matched_prefixes=[],
            span_removed=None,
            blocked_by_safety=False,
        )


def prune_response(
    text: str,
    rules: RuleSources,
    *,
    config: PrunerConfig | None = None,
    strip_comment_keys: bool = False,
) -> PruneResult:
    pruner = Pruner.from_rules(rules, config=config, strip_comment_keys=strip_comment_keys)
    return pruner.prune(text)


class _FrontPruneState:
    def __init__(
        self,
        *,
        text: str,
        offset: int,
        matched_prefixes: list[str],
        units_removed: int,
        blocked_by_safety: bool,
    ) -> None:
        self.text = text
        self.offset = offset
        self.matched_prefixes = matched_prefixes
        self.units_removed = units_removed
        self.blocked_by_safety = blocked_by_safety


class _EndPruneState:
    def __init__(
        self,
        *,
        text: str,
        matched_prefixes: list[str],
        span_removed: tuple[int, int] | None,
        blocked_by_safety: bool,
    ) -> None:
        self.text = text
        self.matched_prefixes = matched_prefixes
        self.span_removed = span_removed
        self.blocked_by_safety = blocked_by_safety


def _normalized_front_prefixes(rules: PruneRules) -> list[tuple[str, str]]:
    if rules.front is None:
        return []

    return [(prefix, normalize_for_prefix_match(prefix)) for prefix in rules.front.prefix]


def _normalized_end_prefixes(rules: PruneRules) -> list[tuple[str, str]]:
    if rules.end is None:
        return []

    return [(prefix, normalize_for_prefix_match(prefix)) for prefix in rules.end.prefix]


def _matching_prefix(text: str, prefixes: list[tuple[str, str]]) -> str | None:
    normalized_text = normalize_for_prefix_match(text)

    for original_prefix, normalized_prefix in prefixes:
        if normalized_text.startswith(normalized_prefix):
            return original_prefix

    return None


def _normalize_response_pruning_config(
    response_pruning: Mapping[str, bool],
    *,
    defaults: dict[str, bool],
) -> dict[str, bool]:
    supported_keys = set(defaults)
    unknown_keys = set(response_pruning) - supported_keys
    if unknown_keys:
        raise PrunerConfigError(
            f"Unsupported response_pruning keys: {sorted(unknown_keys)}"
        )

    normalized = defaults.copy()
    for key, value in response_pruning.items():
        if not isinstance(value, bool):
            raise PrunerConfigError(f"response_pruning.{key} must be a boolean")
        normalized[key] = value

    return normalized
