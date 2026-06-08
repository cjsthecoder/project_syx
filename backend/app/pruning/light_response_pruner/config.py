"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Configuration loading and merging for the light response pruner.

This module validates, loads from JSON files, and merges pruning rule sets into a
single PruneRules model, with optional comment-key stripping and JSON schema export.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .exceptions import RuleConfigError
from .models import EndRuleSection, FrontRuleSection, PruneRules

RuleSource = PruneRules | Mapping[str, Any] | str | Path
RuleSources = RuleSource | Sequence[RuleSource]


def validate_rules(data: Mapping[str, Any] | PruneRules) -> PruneRules:
    """Validate a mapping (or pass through a model) into a PruneRules instance.

    Args:
        data: Raw rule mapping or an already-built PruneRules.

    Returns:
        A validated PruneRules instance.

    Raises:
        RuleConfigError: If the mapping fails Pydantic validation.
    """
    if isinstance(data, PruneRules):
        return data

    try:
        return PruneRules.model_validate(data)
    except ValidationError as exc:
        raise RuleConfigError(f"Invalid pruning rules: {exc}") from exc


def load_rule_file(path: str | Path, *, strip_comment_keys: bool = False) -> PruneRules:
    """Load and validate pruning rules from a JSON file.

    Args:
        path: Path to a JSON file containing a top-level rules object.
        strip_comment_keys: When True, drop keys prefixed with "_comment".

    Returns:
        A validated PruneRules instance.

    Raises:
        RuleConfigError: If the file cannot be read, is invalid JSON, is not a
            JSON object, or fails validation.
    """
    rule_path = Path(path)

    try:
        raw_text = rule_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleConfigError(f"Unable to read rule file '{rule_path}': {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuleConfigError(f"Invalid JSON in rule file '{rule_path}': {exc}") from exc

    if not isinstance(payload, Mapping):
        raise RuleConfigError(
            f"Rule file '{rule_path}' must contain a JSON object at the top level"
        )

    if strip_comment_keys:
        payload = _strip_comment_keys(payload)

    return validate_rules(payload)


def load_rules(sources: RuleSources, *, strip_comment_keys: bool = False) -> PruneRules:
    """Load one or more rule sources and merge them into a single PruneRules.

    Args:
        sources: A single source or sequence of sources; each may be a
            PruneRules, a mapping, or a file path.
        strip_comment_keys: When True, drop "_comment" keys from file sources.

    Returns:
        The merged PruneRules instance.

    Raises:
        RuleConfigError: If no sources are provided or any source is invalid.
    """
    normalized_sources = _normalize_sources(sources)
    rule_sets = [
        _coerce_rule_source(source, strip_comment_keys=strip_comment_keys)
        for source in normalized_sources
    ]
    return merge_rules(rule_sets)


def merge_rules(rule_sets: Sequence[PruneRules]) -> PruneRules:
    """Merge multiple rule sets, unioning prefixes per section.

    Front and end sections are merged independently; their cut modes must agree
    across all sets. A single rule set is returned unchanged.

    Args:
        rule_sets: Rule sets to combine, in priority order.

    Returns:
        The merged PruneRules instance.

    Raises:
        RuleConfigError: If no rule sets are given, cut modes conflict, or the
            merged result fails validation.
    """
    if not rule_sets:
        raise RuleConfigError("At least one rule configuration is required")

    if len(rule_sets) == 1:
        return rule_sets[0]

    merged_front = _merge_front_sections(
        [rule_set.front for rule_set in rule_sets if rule_set.front is not None]
    )
    merged_end = _merge_end_sections(
        [rule_set.end for rule_set in rule_sets if rule_set.end is not None]
    )

    try:
        return PruneRules(front=merged_front, end=merged_end)
    except ValidationError as exc:
        raise RuleConfigError(f"Merged pruning rules are invalid: {exc}") from exc


def export_rules_schema() -> dict[str, Any]:
    """Return the JSON schema for the PruneRules model."""
    return PruneRules.model_json_schema()


def _normalize_sources(sources: RuleSources) -> list[RuleSource]:
    """Wrap a single source in a list and validate that the sequence is non-empty.

    Args:
        sources: A single rule source or a sequence of them.

    Returns:
        A list of one or more rule sources.

    Raises:
        RuleConfigError: If a sequence is provided but contains no sources.
    """
    if isinstance(sources, (PruneRules, Mapping, str, Path)):
        return [sources]

    normalized = list(sources)
    if not normalized:
        raise RuleConfigError("At least one rule source is required")

    return normalized


def _coerce_rule_source(source: RuleSource, *, strip_comment_keys: bool = False) -> PruneRules:
    """Coerce a single rule source into a validated PruneRules.

    Args:
        source: A PruneRules, a mapping, or a path to a JSON rule file.
        strip_comment_keys: When True, drop "_comment" keys from file sources.

    Returns:
        The validated PruneRules for the source.
    """
    if isinstance(source, PruneRules):
        return source

    if isinstance(source, Mapping):
        return validate_rules(source)

    return load_rule_file(source, strip_comment_keys=strip_comment_keys)


def _merge_front_sections(sections: Sequence[FrontRuleSection]) -> FrontRuleSection | None:
    """Union the prefixes of front sections sharing a single cut mode.

    Args:
        sections: Front sections to merge, in priority order.

    Returns:
        A merged FrontRuleSection, or None when no sections are given.

    Raises:
        RuleConfigError: If the sections disagree on ``cut_mode``.
    """
    if not sections:
        return None

    cut_modes = {section.cut_mode for section in sections}
    if len(cut_modes) != 1:
        raise RuleConfigError(f"Conflicting front.cut_mode values found: {sorted(cut_modes)}")

    prefixes = _merge_prefix_lists(section.prefix for section in sections)
    return FrontRuleSection(prefix=prefixes, cut_mode=sections[0].cut_mode)


def _merge_end_sections(sections: Sequence[EndRuleSection]) -> EndRuleSection | None:
    """Union the prefixes of end sections sharing a single cut mode.

    Args:
        sections: End sections to merge, in priority order.

    Returns:
        A merged EndRuleSection, or None when no sections are given.

    Raises:
        RuleConfigError: If the sections disagree on ``cut_mode``.
    """
    if not sections:
        return None

    cut_modes = {section.cut_mode for section in sections}
    if len(cut_modes) != 1:
        raise RuleConfigError(f"Conflicting end.cut_mode values found: {sorted(cut_modes)}")

    prefixes = _merge_prefix_lists(section.prefix for section in sections)
    return EndRuleSection(prefix=prefixes, cut_mode=sections[0].cut_mode)


def _merge_prefix_lists(prefix_lists: Iterable[Sequence[str]]) -> list[str]:
    """Concatenate prefix lists into one, dropping duplicates and keeping order.

    Args:
        prefix_lists: Prefix lists to combine, in priority order.

    Returns:
        The deduplicated, first-seen-order list of prefixes.
    """
    seen: set[str] = set()
    merged: list[str] = []

    for prefix_list in prefix_lists:
        for prefix in prefix_list:
            if prefix in seen:
                continue

            seen.add(prefix)
            merged.append(prefix)

    return merged


def _strip_comment_keys(value: Any) -> Any:
    """Recursively remove "_comment"-prefixed keys from mappings.

    Args:
        value: A mapping, list, or scalar from parsed rule JSON.

    Returns:
        The value with comment keys removed from any nested mappings; scalars
        are returned unchanged.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_comment_keys(child_value)
            for key, child_value in value.items()
            if not str(key).startswith("_comment")
        }

    if isinstance(value, list):
        return [_strip_comment_keys(item) for item in value]

    return value
