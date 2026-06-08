"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
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
    """Validated runtime configuration for the pruning pipeline.

    Holds size/threshold limits, the whitespace mode, and per-stage enable
    flags. All values are validated on construction.
    """

    def __init__(
        self,
        *,
        max_response_size: int = 50_000,
        max_front_units: int = 3,
        similarity_threshold: int = 90,
        whitespace_mode: WhitespaceMode = "compact_prose",
        response_pruning: Mapping[str, bool] | None = None,
    ) -> None:
        """Validate and store pruning configuration.

        Args:
            max_response_size: Maximum input length, in characters, accepted by
                ``prune``; larger inputs are rejected. Must be > 0.
            max_front_units: Maximum number of leading sentences that front
                trimming may remove. Must be > 0.
            similarity_threshold: Fuzzy-match score (0-100) at or above which a
                sentence is treated as a near-duplicate.
            whitespace_mode: Whitespace handling strategy; one of "off",
                "compact_prose", or "preserve_code".
            response_pruning: Optional per-stage enable flags overriding the
                defaults; unknown keys are rejected. When None, all stages are
                enabled.

        Raises:
            PrunerConfigError: If any value has the wrong type or is outside its
                allowed range, or if ``response_pruning`` has unsupported keys.
        """
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
    """Orchestrates the light response pruning pipeline.

    Applies markdown stripping, front/end prefix trimming, whitespace
    compaction, and near-duplicate sentence removal against a set of rules,
    returning a structured PruneResult.
    """

    def __init__(self, *, rules: PruneRules, config: PrunerConfig | None = None) -> None:
        """Initialize the pruner and precompute normalized prefix tables.

        Args:
            rules: Validated front/end prefix rules driving prefix matching.
            config: Optional runtime configuration; a default ``PrunerConfig``
                is used when omitted.
        """
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
        """Build a Pruner from one or more rule sources.

        Args:
            rules: A single source or sequence of PruneRules, mappings, or paths.
            config: Optional runtime configuration; defaults are used if omitted.
            strip_comment_keys: When True, drop "_comment" keys from file sources.

        Returns:
            A configured Pruner instance.
        """
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
        """Build a Pruner from a single rule file (comment keys stripped by default).

        Args:
            path: Path to a JSON rule file.
            config: Optional runtime configuration.
            strip_comment_keys: When True, drop "_comment" keys.

        Returns:
            A configured Pruner instance.
        """
        return cls.from_rules(path, config=config, strip_comment_keys=strip_comment_keys)

    @classmethod
    def from_files(
        cls,
        paths: Sequence[str | Path],
        *,
        config: PrunerConfig | None = None,
        strip_comment_keys: bool = True,
    ) -> "Pruner":
        """Build a Pruner from multiple rule files (comment keys stripped by default).

        Args:
            paths: Paths to JSON rule files, in priority order.
            config: Optional runtime configuration.
            strip_comment_keys: When True, drop "_comment" keys.

        Returns:
            A configured Pruner instance with merged rules.
        """
        return cls.from_rules(list(paths), config=config, strip_comment_keys=strip_comment_keys)

    def prune(self, text: str) -> PruneResult:
        """Run the configured pruning stages over ``text``.

        Stages run in order (markdown, front, end, whitespace, similarity) and
        each is skipped when disabled in the config. A safety guard prevents
        trimming that would leave the text empty.

        Args:
            text: The response text to prune.

        Returns:
            A PruneResult describing the pruned text and what changed.

        Raises:
            PrunerInputError: If ``text`` is not a string or exceeds the
                configured ``max_response_size``.
        """
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
        """Trim matching leading sentences from the front of ``text``.

        Iterates leading sentences up to ``max_front_units``, removing each one
        whose normalized prefix matches a configured front prefix. Stops early
        when removal would empty the remaining text, flagging the safety guard.

        Args:
            text: Working response text to trim from the front.

        Returns:
            A ``_FrontPruneState`` capturing the remaining text, consumed
            offset, matched prefixes, count removed, and the safety flag.
        """
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
        """Trim a trailing paragraph whose prefix matches a configured end rule.

        Considers only the last two paragraphs, skipping those inside fenced
        code or beginning with structured content. Removal is blocked (and the
        safety flag set) when it would empty the remaining text.

        Args:
            text: Working response text to trim from the end.
            original_offset: Offset of ``text`` within the original response,
                used to report removed spans in original coordinates.

        Returns:
            An ``_EndPruneState`` capturing the remaining text, matched
            prefixes, removed span (or None), and the safety flag.
        """
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
    """Prune ``text`` using ``rules`` in a single convenience call.

    Args:
        text: The response text to prune.
        rules: Rule source(s) accepted by ``Pruner.from_rules``.
        config: Optional runtime configuration.
        strip_comment_keys: When True, drop "_comment" keys from file sources.

    Returns:
        A PruneResult describing the pruned text and what changed.
    """
    pruner = Pruner.from_rules(rules, config=config, strip_comment_keys=strip_comment_keys)
    return pruner.prune(text)


class _FrontPruneState:
    """Internal result of a front-trimming pass.

    Attributes:
        text: Response text after front trimming.
        offset: Character offset of ``text`` within the pre-trim string.
        matched_prefixes: Front prefixes that matched and drove removal.
        units_removed: Number of leading sentences removed.
        blocked_by_safety: True when trimming was suppressed by a safety guard.
    """

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
    """Internal result of an end-trimming pass.

    Attributes:
        text: Response text after end trimming.
        matched_prefixes: End prefixes that matched and drove removal.
        span_removed: ``(start, end)`` character span removed, or ``None`` when
            nothing was trimmed.
        blocked_by_safety: True when trimming was suppressed by a safety guard.
    """

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
    """Pair each front prefix with its normalized comparison form.

    Args:
        rules: Rules whose front section supplies the prefixes.

    Returns:
        ``(original, normalized)`` pairs, or an empty list when no front section
        is configured.
    """
    if rules.front is None:
        return []

    return [(prefix, normalize_for_prefix_match(prefix)) for prefix in rules.front.prefix]


def _normalized_end_prefixes(rules: PruneRules) -> list[tuple[str, str]]:
    """Pair each end prefix with its normalized comparison form.

    Args:
        rules: Rules whose end section supplies the prefixes.

    Returns:
        ``(original, normalized)`` pairs, or an empty list when no end section
        is configured.
    """
    if rules.end is None:
        return []

    return [(prefix, normalize_for_prefix_match(prefix)) for prefix in rules.end.prefix]


def _matching_prefix(text: str, prefixes: list[tuple[str, str]]) -> str | None:
    """Return the first original prefix whose normalized form starts ``text``.

    Args:
        text: Candidate text to test (normalized internally before matching).
        prefixes: ``(original, normalized)`` prefix pairs to test in order.

    Returns:
        The matching original prefix, or None when none match.
    """
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
    """Merge user response-pruning flags onto the defaults, validating them.

    Args:
        response_pruning: Per-stage enable flags supplied by the caller.
        defaults: Full set of supported flags with their default values.

    Returns:
        A new dict of defaults overlaid with the provided flag values.

    Raises:
        PrunerConfigError: If unsupported keys are present or any value is not a
            boolean.
    """
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
