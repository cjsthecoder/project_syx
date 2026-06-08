"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Pydantic models for the light response pruner.

Defines the rule configuration models (front/end cut sections and prune rules)
and the structured result type returned when pruning a response.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

FrontCutMode = Literal["sentence"]
EndCutMode = Literal["paragraph_to_end"]
TrimmedSide = Literal["none", "front", "end", "both"]
WhitespaceMode = Literal["off", "compact_prose", "preserve_code"]


def _dedupe_prefixes(prefixes: list[str]) -> list[str]:
    """Strip and de-duplicate prefixes, preserving order.

    Args:
        prefixes: Raw prefix strings to clean.

    Returns:
        Stripped prefixes with duplicates removed, in first-seen order.

    Raises:
        ValueError: If any prefix is blank after stripping.
    """
    seen: set[str] = set()
    deduped: list[str] = []

    for prefix in prefixes:
        cleaned = prefix.strip()
        if not cleaned:
            raise ValueError("prefix entries must not be blank")

        if cleaned in seen:
            continue

        seen.add(cleaned)
        deduped.append(cleaned)

    return deduped


class FrontRuleSection(BaseModel):
    """Front-trimming rules: prefixes and the cut mode applied at the start.

    A leading sentence is removed when it begins with one of the configured
    prefixes; ``cut_mode`` fixes the unit of removal. Prefixes are stripped and
    de-duplicated on validation, and ``extra`` keys are forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    prefix: list[str] = Field(min_length=1)
    cut_mode: FrontCutMode

    @field_validator("prefix")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        """Strip and de-duplicate the configured front prefixes.

        Args:
            value: Raw prefix list supplied during validation.

        Returns:
            The cleaned, de-duplicated prefix list.
        """
        return _dedupe_prefixes(value)


class EndRuleSection(BaseModel):
    """End-trimming rules: prefixes and the cut mode applied at the tail.

    A trailing paragraph is removed when it begins with one of the configured
    prefixes; ``cut_mode`` fixes the unit of removal. Prefixes are stripped and
    de-duplicated on validation, and ``extra`` keys are forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    prefix: list[str] = Field(min_length=1)
    cut_mode: EndCutMode

    @field_validator("prefix")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        """Strip and de-duplicate the configured end prefixes.

        Args:
            value: Raw prefix list supplied during validation.

        Returns:
            The cleaned, de-duplicated prefix list.
        """
        return _dedupe_prefixes(value)


class PruneRules(BaseModel):
    """Top-level rule set driving the pruner's prefix-based trimming.

    Holds optional front and end sections. Validation enforces the invariant
    that at least one section is present, so an empty rule set cannot be
    constructed; ``extra`` keys are forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    front: FrontRuleSection | None = None
    end: EndRuleSection | None = None

    @model_validator(mode="after")
    def require_one_section(self) -> "PruneRules":
        """Enforce that at least one of ``front`` or ``end`` is configured.

        Returns:
            The validated model instance.

        Raises:
            ValueError: If both sections are absent.
        """
        if self.front is None and self.end is None:
            raise ValueError("at least one of 'front' or 'end' must be provided")

        return self


class PruneResult(BaseModel):
    """Structured outcome of a single prune operation.

    Reports both the original and pruned text and a full audit of what changed:
    which sides were trimmed, which prefixes matched, how much was removed, and
    whether a safety guard blocked trimming. The ``trimmed_side`` computed field
    summarizes the trimmed sides for consumers.
    """

    model_config = ConfigDict(extra="forbid")

    original_text: str
    pruned_text: str
    changed: bool = False
    trimmed_front: bool = False
    trimmed_end: bool = False
    matched_front_prefixes: list[str] = Field(default_factory=list)
    matched_end_prefixes: list[str] = Field(default_factory=list)
    front_units_removed: int = 0
    end_span_removed: tuple[int, int] | None = None
    blocked_by_safety: bool = False

    @computed_field(return_type=str)
    def trimmed_side(self) -> TrimmedSide:
        """Return which side(s) were trimmed: "both", "front", "end", or "none"."""
        if self.trimmed_front and self.trimmed_end:
            return "both"

        if self.trimmed_front:
            return "front"

        if self.trimmed_end:
            return "end"

        return "none"
