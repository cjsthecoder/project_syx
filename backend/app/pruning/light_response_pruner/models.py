"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

FrontCutMode = Literal["sentence"]
EndCutMode = Literal["paragraph_to_end"]
TrimmedSide = Literal["none", "front", "end", "both"]
WhitespaceMode = Literal["off", "compact_prose", "preserve_code"]


def _dedupe_prefixes(prefixes: list[str]) -> list[str]:
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
    model_config = ConfigDict(extra="forbid")

    prefix: list[str] = Field(min_length=1)
    cut_mode: FrontCutMode

    @field_validator("prefix")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        return _dedupe_prefixes(value)


class EndRuleSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: list[str] = Field(min_length=1)
    cut_mode: EndCutMode

    @field_validator("prefix")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        return _dedupe_prefixes(value)


class PruneRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    front: FrontRuleSection | None = None
    end: EndRuleSection | None = None

    @model_validator(mode="after")
    def require_one_section(self) -> "PruneRules":
        if self.front is None and self.end is None:
            raise ValueError("at least one of 'front' or 'end' must be provided")

        return self


class PruneResult(BaseModel):
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
        if self.trimmed_front and self.trimmed_end:
            return "both"

        if self.trimmed_front:
            return "front"

        if self.trimmed_end:
            return "end"

        return "none"
