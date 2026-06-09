"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for app.pruning.light_response_pruner.rules.

Covers rule loading/validation from mappings, JSON files, and PruneRules
instances; multi-source loading and merging (prefix union, cut-mode agreement);
comment-key stripping; schema export; and the error paths that raise
``RuleConfigError``.
"""

import json

import pytest
from app.pruning.light_response_pruner.exceptions import RuleConfigError
from app.pruning.light_response_pruner.models import (
    EndRuleSection,
    FrontRuleSection,
    PruneRules,
)
from app.pruning.light_response_pruner.rules import (
    _merge_end_sections,
    _merge_front_sections,
    _merge_prefix_lists,
    _strip_comment_keys,
    export_rules_schema,
    load_rule_file,
    load_rules,
    merge_rules,
    validate_rules,
)


def _front(prefixes):
    return {"prefix": list(prefixes), "cut_mode": "sentence"}


def _end(prefixes):
    return {"prefix": list(prefixes), "cut_mode": "paragraph_to_end"}


# --- validate_rules -------------------------------------------------------


def test_validate_rules_passes_through_model():
    rules = PruneRules(front=FrontRuleSection(prefix=["Sure"], cut_mode="sentence"))
    assert validate_rules(rules) is rules


def test_validate_rules_builds_from_mapping():
    out = validate_rules({"front": _front(["Sure,"])})
    assert isinstance(out, PruneRules)
    assert out.front is not None
    assert out.front.prefix == ["Sure,"]


def test_validate_rules_invalid_mapping_raises():
    # Both sections missing -> model_validator rejects -> RuleConfigError.
    with pytest.raises(RuleConfigError):
        validate_rules({})


# --- load_rule_file -------------------------------------------------------


def test_load_rule_file_happy(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"front": _front(["Sure"])}), encoding="utf-8")
    out = load_rule_file(path)
    assert out.front is not None
    assert out.front.prefix == ["Sure"]


def test_load_rule_file_missing_file_raises(tmp_path):
    with pytest.raises(RuleConfigError, match="Unable to read"):
        load_rule_file(tmp_path / "nope.json")


def test_load_rule_file_invalid_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(RuleConfigError, match="Invalid JSON"):
        load_rule_file(path)


def test_load_rule_file_non_object_top_level_raises(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(RuleConfigError, match="must contain a JSON object"):
        load_rule_file(path)


def test_load_rule_file_strips_comment_keys(tmp_path):
    path = tmp_path / "commented.json"
    payload = {
        "_comment": "top-level note",
        "front": {"_comment_x": "drop me", "prefix": ["Sure"], "cut_mode": "sentence"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    out = load_rule_file(path, strip_comment_keys=True)
    assert out.front is not None
    assert out.front.prefix == ["Sure"]


# --- load_rules -----------------------------------------------------------


def test_load_rules_single_mapping_source():
    out = load_rules({"end": _end(["Note:"])})
    assert out.end is not None
    assert out.end.prefix == ["Note:"]


def test_load_rules_merges_multiple_sources(tmp_path):
    file_source = tmp_path / "a.json"
    file_source.write_text(json.dumps({"front": _front(["Sure"])}), encoding="utf-8")
    model_source = PruneRules(front=FrontRuleSection(prefix=["Certainly"], cut_mode="sentence"))
    out = load_rules([file_source, model_source, {"end": _end(["Note:"])}])
    assert out.front is not None
    assert out.front.prefix == ["Sure", "Certainly"]  # unioned, first-seen order
    assert out.end is not None
    assert out.end.prefix == ["Note:"]


def test_load_rules_empty_sequence_raises():
    with pytest.raises(RuleConfigError, match="At least one rule source"):
        load_rules([])


# --- merge_rules ----------------------------------------------------------


def test_merge_rules_requires_at_least_one():
    with pytest.raises(RuleConfigError, match="At least one rule configuration"):
        merge_rules([])


def test_merge_rules_single_set_returned_unchanged():
    only = PruneRules(front=FrontRuleSection(prefix=["Sure"], cut_mode="sentence"))
    assert merge_rules([only]) is only


def test_merge_rules_unions_front_and_end():
    a = PruneRules(
        front=FrontRuleSection(prefix=["Sure", "Of course"], cut_mode="sentence"),
        end=EndRuleSection(prefix=["Note:"], cut_mode="paragraph_to_end"),
    )
    b = PruneRules(
        front=FrontRuleSection(prefix=["Of course", "Certainly"], cut_mode="sentence"),
        end=EndRuleSection(prefix=["Caveat:"], cut_mode="paragraph_to_end"),
    )
    merged = merge_rules([a, b])
    assert merged.front is not None
    assert merged.front.prefix == ["Sure", "Of course", "Certainly"]  # dedup union
    assert merged.end is not None
    assert merged.end.prefix == ["Note:", "Caveat:"]


def test_merge_rules_raises_when_merged_result_invalid():
    # Two section-less sets (forced via model_construct, bypassing the
    # at-least-one-section invariant) merge to an empty result that fails
    # PruneRules validation -> RuleConfigError.
    empty1 = PruneRules.model_construct(front=None, end=None)
    empty2 = PruneRules.model_construct(front=None, end=None)
    with pytest.raises(RuleConfigError, match="Merged pruning rules are invalid"):
        merge_rules([empty1, empty2])


def test_merge_rules_front_only_when_no_end_sections():
    a = PruneRules(front=FrontRuleSection(prefix=["Sure"], cut_mode="sentence"))
    b = PruneRules(front=FrontRuleSection(prefix=["Certainly"], cut_mode="sentence"))
    merged = merge_rules([a, b])
    assert merged.end is None
    assert merged.front is not None
    assert merged.front.prefix == ["Sure", "Certainly"]


# --- section merge helpers ------------------------------------------------


def test_merge_front_sections_none_when_empty():
    assert _merge_front_sections([]) is None


def test_merge_end_sections_none_when_empty():
    assert _merge_end_sections([]) is None


def test_merge_front_sections_conflicting_cut_mode_raises():
    # cut_mode is a single-value Literal in normal use; force a conflict via
    # model_construct to exercise the defensive agreement check.
    s1 = FrontRuleSection(prefix=["Sure"], cut_mode="sentence")
    s2 = FrontRuleSection.model_construct(prefix=["Certainly"], cut_mode="other")
    with pytest.raises(RuleConfigError, match="Conflicting front.cut_mode"):
        _merge_front_sections([s1, s2])


def test_merge_end_sections_conflicting_cut_mode_raises():
    s1 = EndRuleSection(prefix=["Note:"], cut_mode="paragraph_to_end")
    s2 = EndRuleSection.model_construct(prefix=["Caveat:"], cut_mode="other")
    with pytest.raises(RuleConfigError, match="Conflicting end.cut_mode"):
        _merge_end_sections([s1, s2])


# --- _merge_prefix_lists --------------------------------------------------


def test_merge_prefix_lists_dedupes_preserving_order():
    out = _merge_prefix_lists([["a", "b"], ["b", "c"], ["a", "d"]])
    assert out == ["a", "b", "c", "d"]


# --- _strip_comment_keys --------------------------------------------------


def test_strip_comment_keys_recurses_mappings_and_lists():
    value = {
        "_comment": "drop",
        "keep": 1,
        "nested": {"_comment_inner": "drop", "ok": 2},
        "items": [{"_comment": "drop", "v": 3}, "scalar"],
    }
    out = _strip_comment_keys(value)
    assert out == {"keep": 1, "nested": {"ok": 2}, "items": [{"v": 3}, "scalar"]}


def test_strip_comment_keys_passes_scalars_through():
    assert _strip_comment_keys(42) == 42
    assert _strip_comment_keys("text") == "text"


# --- export_rules_schema --------------------------------------------------


def test_export_rules_schema_returns_json_schema():
    schema = export_rules_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "front" in schema["properties"]
    assert "end" in schema["properties"]
