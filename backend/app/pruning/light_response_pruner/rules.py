"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Loading, validation, and merging of pruning rule configurations.

Reads rules from mappings, JSON files, or PruneRules instances, validates them
against the Pydantic models, and merges multiple rule sources into one.
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
    if isinstance(data, PruneRules):
        return data

    try:
        return PruneRules.model_validate(data)
    except ValidationError as exc:
        raise RuleConfigError(f"Invalid pruning rules: {exc}") from exc


def load_rule_file(path: str | Path, *, strip_comment_keys: bool = False) -> PruneRules:
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
    normalized_sources = _normalize_sources(sources)
    rule_sets = [
        _coerce_rule_source(source, strip_comment_keys=strip_comment_keys)
        for source in normalized_sources
    ]
    return merge_rules(rule_sets)


def merge_rules(rule_sets: Sequence[PruneRules]) -> PruneRules:
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
    return PruneRules.model_json_schema()


def _normalize_sources(sources: RuleSources) -> list[RuleSource]:
    if isinstance(sources, (PruneRules, Mapping, str, Path)):
        return [sources]

    normalized = list(sources)
    if not normalized:
        raise RuleConfigError("At least one rule source is required")

    return normalized


def _coerce_rule_source(source: RuleSource, *, strip_comment_keys: bool = False) -> PruneRules:
    if isinstance(source, PruneRules):
        return source

    if isinstance(source, Mapping):
        return validate_rules(source)

    return load_rule_file(source, strip_comment_keys=strip_comment_keys)


def _merge_front_sections(sections: Sequence[FrontRuleSection]) -> FrontRuleSection | None:
    if not sections:
        return None

    cut_modes = {section.cut_mode for section in sections}
    if len(cut_modes) != 1:
        raise RuleConfigError(f"Conflicting front.cut_mode values found: {sorted(cut_modes)}")

    prefixes = _merge_prefix_lists(section.prefix for section in sections)
    return FrontRuleSection(prefix=prefixes, cut_mode=sections[0].cut_mode)


def _merge_end_sections(sections: Sequence[EndRuleSection]) -> EndRuleSection | None:
    if not sections:
        return None

    cut_modes = {section.cut_mode for section in sections}
    if len(cut_modes) != 1:
        raise RuleConfigError(f"Conflicting end.cut_mode values found: {sorted(cut_modes)}")

    prefixes = _merge_prefix_lists(section.prefix for section in sections)
    return EndRuleSection(prefix=prefixes, cut_mode=sections[0].cut_mode)


def _merge_prefix_lists(prefix_lists: Iterable[Sequence[str]]) -> list[str]:
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
    if isinstance(value, Mapping):
        return {
            key: _strip_comment_keys(child_value)
            for key, child_value in value.items()
            if not str(key).startswith("_comment")
        }

    if isinstance(value, list):
        return [_strip_comment_keys(item) for item in value]

    return value
