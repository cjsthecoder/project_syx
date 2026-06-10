"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Targeted coverage tests for the light response pruner internals.

These exercise the remaining error/edge branches across the package's modules:
config loading/merging fail-fast paths, model validators, the PrunerConfig
guards and pipeline convenience helpers, and the low-level span/whitespace/
similarity helpers. They are deliberately small and direct (calling helpers
where useful) to complement the behavior-level tests in test_pruning.py.
"""
import json
from pathlib import Path

import pytest
from app.pruning.light_response_pruner.config import (
    _coerce_rule_source,
    _merge_end_sections,
    _merge_front_sections,
    _merge_prefix_lists,
    _normalize_sources,
    export_rules_schema,
    load_rule_file,
    load_rules,
    merge_rules,
    validate_rules,
)
from app.pruning.light_response_pruner.exceptions import (
    PrunerConfigError,
    PrunerInputError,
    RuleConfigError,
)
from app.pruning.light_response_pruner.models import (
    EndRuleSection,
    FrontRuleSection,
    PruneResult,
    PruneRules,
)
from app.pruning.light_response_pruner.pruner import (
    Pruner,
    PrunerConfig,
    prune_response,
)
from app.pruning.light_response_pruner.similarity import (
    _sentence_spans,
    prune_similar_sentences,
)
from app.pruning.light_response_pruner.units import (
    _is_inside_fenced_code_block,
    _starts_with_ordered_list_marker,
    leading_sentence_span,
    paragraph_spans,
)
from app.pruning.light_response_pruner.whitespace import compact_whitespace

_FRONT = {"front": {"prefix": ["sure"], "cut_mode": "sentence"}}
_END = {"end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"}}


# --- config.validate_rules / load_rule_file --------------------------------


def test_validate_rules_passthrough_model():
    rules = PruneRules(front=FrontRuleSection(prefix=["sure"], cut_mode="sentence"))
    assert validate_rules(rules) is rules


def test_validate_rules_invalid_raises():
    with pytest.raises(RuleConfigError):
        validate_rules({"front": {"prefix": [], "cut_mode": "sentence"}})


def test_load_rule_file_missing_raises(tmp_path):
    with pytest.raises(RuleConfigError, match="Unable to read"):
        load_rule_file(tmp_path / "nope.json")


def test_load_rule_file_invalid_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuleConfigError, match="Invalid JSON"):
        load_rule_file(p)


def test_load_rule_file_non_object_raises(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RuleConfigError, match="JSON object"):
        load_rule_file(p)


def test_load_rule_file_strips_comment_keys(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(
        json.dumps(
            {"_comment": "ignore me", "front": {"prefix": ["sure"], "cut_mode": "sentence"}}
        ),
        encoding="utf-8",
    )
    rules = load_rule_file(p, strip_comment_keys=True)
    assert rules.front is not None and rules.front.prefix == ["sure"]


# --- config.load_rules / merge_rules ---------------------------------------


def test_load_rules_single_model_passthrough():
    rules = PruneRules(front=FrontRuleSection(prefix=["sure"], cut_mode="sentence"))
    assert load_rules(rules) is rules


def test_merge_rules_empty_raises():
    with pytest.raises(RuleConfigError, match="At least one rule configuration"):
        merge_rules([])


def test_merge_rules_combines_front_and_end():
    a = validate_rules(_FRONT)
    b = validate_rules(_END)
    merged = merge_rules([a, b])
    assert merged.front is not None and merged.front.prefix == ["sure"]
    assert merged.end is not None and merged.end.prefix == ["let me know"]


def test_merge_rules_unions_prefixes_same_section():
    a = validate_rules({"front": {"prefix": ["sure"], "cut_mode": "sentence"}})
    b = validate_rules({"front": {"prefix": ["okay", "sure"], "cut_mode": "sentence"}})
    merged = merge_rules([a, b])
    assert merged.front is not None and merged.front.prefix == ["sure", "okay"]


def test_merge_front_sections_conflicting_cut_mode_raises(monkeypatch):
    # Two front sections whose cut_mode differs -> conflict. (Construct via
    # model_construct to bypass the Literal validator and force the branch.)
    s1 = FrontRuleSection(prefix=["a"], cut_mode="sentence")
    s2 = FrontRuleSection.model_construct(prefix=["b"], cut_mode="other")
    with pytest.raises(RuleConfigError, match="Conflicting front.cut_mode"):
        _merge_front_sections([s1, s2])


def test_merge_end_sections_conflicting_cut_mode_raises():
    s1 = EndRuleSection(prefix=["a"], cut_mode="paragraph_to_end")
    s2 = EndRuleSection.model_construct(prefix=["b"], cut_mode="other")
    with pytest.raises(RuleConfigError, match="Conflicting end.cut_mode"):
        _merge_end_sections([s1, s2])


def test_merge_front_and_end_sections_empty_returns_none():
    assert _merge_front_sections([]) is None
    assert _merge_end_sections([]) is None


def test_merge_prefix_lists_dedupes_in_order():
    assert _merge_prefix_lists([["a", "b"], ["b", "c"]]) == ["a", "b", "c"]


def test_export_rules_schema_returns_dict():
    schema = export_rules_schema()
    assert isinstance(schema, dict) and "properties" in schema


# --- config._normalize_sources / _coerce_rule_source -----------------------


def test_normalize_sources_wraps_single():
    assert _normalize_sources(_FRONT) == [_FRONT]


def test_normalize_sources_list_passthrough():
    assert _normalize_sources([_FRONT, _END]) == [_FRONT, _END]


def test_normalize_sources_empty_sequence_raises():
    with pytest.raises(RuleConfigError, match="At least one rule source"):
        _normalize_sources([])


def test_coerce_rule_source_model_passthrough():
    rules = PruneRules(front=FrontRuleSection(prefix=["sure"], cut_mode="sentence"))
    assert _coerce_rule_source(rules) is rules


# --- models ----------------------------------------------------------------


def test_front_rule_section_blank_prefix_raises():
    with pytest.raises(ValueError, match="must not be blank"):
        FrontRuleSection(prefix=["  "], cut_mode="sentence")


def test_front_rule_section_dedupes_prefixes():
    section = FrontRuleSection(prefix=["sure", "sure", "okay"], cut_mode="sentence")
    assert section.prefix == ["sure", "okay"]


def test_prune_result_trimmed_side_front_only():
    res = PruneResult(original_text="x", pruned_text="y", trimmed_front=True)
    assert res.trimmed_side == "front"


def test_prune_result_trimmed_side_end_only():
    res = PruneResult(original_text="x", pruned_text="y", trimmed_end=True)
    assert res.trimmed_side == "end"


def test_prune_result_trimmed_side_none():
    res = PruneResult(original_text="x", pruned_text="x")
    assert res.trimmed_side == "none"


# --- PrunerConfig guards ---------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"max_response_size": "big"}, "max_response_size must be an int"),
        ({"max_response_size": 0}, "greater than 0"),
        ({"max_front_units": "lots"}, "max_front_units must be an int"),
        ({"max_front_units": 0}, "greater than 0"),
        ({"similarity_threshold": "high"}, "similarity_threshold must be an int"),
    ],
)
def test_pruner_config_invalid_values_raise(kwargs, match):
    with pytest.raises(PrunerConfigError, match=match):
        PrunerConfig(**kwargs)


# --- Pruner.from_files / prune input guards / prune_response ---------------


def _write_rule_file(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_pruner_from_file_single(tmp_path):
    f1 = _write_rule_file(tmp_path, "front.json", _FRONT)
    pruner = Pruner.from_file(f1)
    assert pruner.rules.front is not None and pruner.rules.front.prefix == ["sure"]


def test_pruner_from_files_merges(tmp_path):
    f1 = _write_rule_file(tmp_path, "front.json", _FRONT)
    f2 = _write_rule_file(tmp_path, "end.json", _END)
    pruner = Pruner.from_files([f1, f2])
    assert pruner.rules.front is not None and pruner.rules.end is not None


def test_prune_non_string_raises():
    pruner = Pruner.from_rules(_FRONT)
    with pytest.raises(PrunerInputError, match="must be a string"):
        pruner.prune(123)  # type: ignore[arg-type]


def test_prune_oversized_raises(caplog):
    pruner = Pruner.from_rules(_FRONT, config=PrunerConfig(max_response_size=10))
    with pytest.raises(PrunerInputError, match="exceeds configured"):
        pruner.prune("x" * 50)
    assert any("exceeds configured max_response_size" in r.message for r in caplog.records)


def test_prune_response_convenience():
    result = prune_response("Sure. The answer stays.", _FRONT)
    assert result.pruned_text == "The answer stays."


# --- pruner._prune_end fenced-code skip + safety block ---------------------


def test_prune_end_skips_paragraph_inside_fenced_code_block():
    # The trailing matching paragraph sits inside an open fence (the paragraph
    # itself does not start with a structural marker), so the end-trim must skip
    # it via span_starts_inside_fenced_code_block -> continue.
    rules = {"end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"}}
    config = PrunerConfig(
        whitespace_mode="off",
        response_pruning={
            "enabled": True,
            "front_enabled": False,
            "end_enabled": True,
            "whitespace_enabled": False,
            "similarity_enabled": False,
        },
    )
    text = "```\ncode\n\nlet me know if this helps\n"
    result = Pruner.from_rules(rules, config=config).prune(text)
    assert result.trimmed_end is False


def test_prune_end_blocked_when_removal_would_empty():
    # The only paragraph matches the end prefix; trimming it would empty the
    # text, so the safety guard blocks removal.
    rules = {"end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"}}
    result = Pruner.from_rules(rules, config=PrunerConfig(whitespace_mode="off")).prune(
        "Let me know if this helps."
    )
    assert result.trimmed_end is False
    assert result.blocked_by_safety is True


# --- units helpers ---------------------------------------------------------


def test_leading_sentence_span_blank_text_is_none():
    assert leading_sentence_span("   \n  ") is None


def test_leading_sentence_span_skips_non_terminal_dot():
    # The dot in "v1.2" is followed by a digit, so it is not a sentence end;
    # the real terminator is the trailing period.
    span = leading_sentence_span("Version v1.2 shipped today. Next item.")
    assert span is not None and span.text == "Version v1.2 shipped today."


def test_paragraph_spans_skips_leading_blank_segment_and_trims_trailing_ws():
    spans = paragraph_spans("\n\nabc   \n\ndef")
    assert [s.text for s in spans] == ["abc", "def"]


def test_is_inside_fenced_code_block_toggles_on_fence():
    text = "```\ncode here\n"
    assert _is_inside_fenced_code_block(text, len(text)) is True


def test_starts_with_ordered_list_marker_variants():
    assert _starts_with_ordered_list_marker("12. item") is True
    assert _starts_with_ordered_list_marker("12 no dot") is False
    assert _starts_with_ordered_list_marker("123") is False


# --- similarity helpers ----------------------------------------------------


def test_prune_similar_sentences_blank_passthrough():
    assert prune_similar_sentences("   ") == "   "


def test_prune_similar_sentences_drops_dup_before_fence_adds_newline():
    # A dropped duplicate before a code fence leaves rstripped prose with no
    # trailing newline, so a newline is reinserted before the fence.
    text = "The cat sat. The cat sat.\n```\ncode\n```\n"
    out = prune_similar_sentences(text, threshold=90)
    assert "```" in out
    assert out.count("The cat sat.") == 1


def test_sentence_spans_blank_returns_empty():
    assert _sentence_spans("   ") == []


# --- whitespace ------------------------------------------------------------


def test_compact_whitespace_blank_returns_empty():
    assert compact_whitespace("   \n  ") == ""
