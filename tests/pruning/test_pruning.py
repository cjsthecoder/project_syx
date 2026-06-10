"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the light response pruner.

Exercises ``light_response_pruner`` behaviors: front/end prefix trimming,
whitespace compaction, similar-sentence deduplication, fenced-code-block
safety, per-stage enable toggles, and config validation.
"""
from typing import cast

import pytest
from app.pruning.light_response_pruner import (
    Pruner,
    PrunerConfig,
    PrunerConfigError,
    compact_whitespace,
    normalize_for_prefix_match,
    prune_similar_sentences,
)


def test_normalize_for_prefix_match_follows_requirement_order() -> None:
    assert normalize_for_prefix_match("  YOU\u2019RE   RIGHT!\n") == "you're right"


def test_front_pruning_removes_matching_leading_sentence() -> None:
    pruner = Pruner.from_rules({"front": {"prefix": ["you're right"], "cut_mode": "sentence"}})

    result = pruner.prune("You\u2019re right. The substantive answer stays.")

    assert result.pruned_text == "The substantive answer stays."
    assert result.changed is True
    assert result.trimmed_front is True
    assert result.matched_front_prefixes == ["you're right"]
    assert result.front_units_removed == 1


def test_front_pruning_respects_max_front_units() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["got it", "absolutely"], "cut_mode": "sentence"}},
        config=PrunerConfig(max_front_units=1),
    )

    result = pruner.prune("Got it. Absolutely. The substantive answer stays.")

    assert result.pruned_text == "Absolutely. The substantive answer stays."
    assert result.front_units_removed == 1


def test_front_pruning_blocks_empty_result() -> None:
    pruner = Pruner.from_rules({"front": {"prefix": ["got it"], "cut_mode": "sentence"}})

    result = pruner.prune("Got it.")

    assert result.pruned_text == "Got it."
    assert result.changed is False
    assert result.blocked_by_safety is True


def test_front_pruning_noop_when_no_leading_sentence_span() -> None:
    # Text without terminal punctuation yields no leading sentence span, so the
    # front-trim loop breaks immediately and the text is returned unchanged.
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["got it"], "cut_mode": "sentence"}},
        config=PrunerConfig(whitespace_mode="off"),
    )

    result = pruner.prune("got it with no terminating punctuation")

    assert result.pruned_text == "got it with no terminating punctuation"
    assert result.changed is False
    assert result.trimmed_front is False


def test_end_pruning_removes_matching_paragraph_to_end() -> None:
    pruner = Pruner.from_rules({"end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"}})
    text = "The substantive answer stays.\n\nLet me know if you want more examples."

    result = pruner.prune(text)

    assert result.pruned_text == "The substantive answer stays."
    assert result.changed is True
    assert result.trimmed_end is True
    assert result.matched_end_prefixes == ["let me know"]
    assert result.end_span_removed == (31, len(text))


def test_combined_front_and_end_pruning() -> None:
    pruner = Pruner.from_rules(
        {
            "front": {"prefix": ["got it"], "cut_mode": "sentence"},
            "end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"},
        }
    )

    result = pruner.prune(
        "Got it. The substantive answer stays.\n\nLet me know if you want more examples."
    )

    assert result.pruned_text == "The substantive answer stays."
    assert result.trimmed_side == "both"


def test_end_pruning_skips_matching_prefix_inside_fenced_code_block() -> None:
    pruner = Pruner.from_rules(
        {"end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"}},
        config=PrunerConfig(whitespace_mode="off"),
    )
    text = 'The substantive answer stays.\n\n```\nLet me know = "not boilerplate"\n```'

    result = pruner.prune(text)

    assert result.pruned_text == text
    assert result.changed is False


def test_end_pruning_ignores_matching_middle_paragraph() -> None:
    pruner = Pruner.from_rules(
        {"end": {"prefix": ["if you want"], "cut_mode": "paragraph_to_end"}},
        config=PrunerConfig(whitespace_mode="off"),
    )
    text = (
        "Paragraph one with substantive content.\n\n"
        "If you want to keep this note in the middle, do not trim here.\n\n"
        "Paragraph three continues substantive content.\n\n"
        "Final paragraph without end-trigger language."
    )

    result = pruner.prune(text)

    assert result.pruned_text == text
    assert result.changed is False


def test_compact_whitespace_preserves_fenced_code_block_contents() -> None:
    text = (
        "A   spaced\tline.\n\n\n"
        "```python\n"
        "x  =   1\n"
        "print(x)\n"
        "```\n\n"
        "Another\t\tline."
    )

    result = compact_whitespace(text)

    assert result == (
        "A spaced line.\n" "\n" "```python\n" "x  =   1\n" "print(x)\n" "```\n" "\n" "Another line."
    )


def test_compact_whitespace_unbalanced_fence_preserves_remainder_as_code() -> None:
    text = "Intro   line.\n```python\nx  =   1\nprint(x)\n"

    result = compact_whitespace(text)

    assert result == "Intro line.\n```python\nx  =   1\nprint(x)"


def test_pruner_compacts_whitespace_after_pruning() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["got it"], "cut_mode": "sentence"}},
        config=PrunerConfig(whitespace_mode="compact_prose"),
    )

    result = pruner.prune("Got it.  Keep   this.\n\n\nAnd this.")

    assert result.pruned_text == "Keep this.\n\nAnd this."


def test_pruner_whitespace_mode_off_skips_compaction() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["got it"], "cut_mode": "sentence"}},
        config=PrunerConfig(whitespace_mode="off"),
    )

    result = pruner.prune("Got it.  Keep   this.\n\n\nAnd this.")

    assert result.pruned_text == "Keep   this.\n\n\nAnd this."


def test_pruner_config_rejects_invalid_whitespace_mode() -> None:
    with pytest.raises(PrunerConfigError):
        PrunerConfig(whitespace_mode="invalid")  # type: ignore[arg-type]


def test_response_pruning_defaults_all_true() -> None:
    config = PrunerConfig()
    assert config.response_pruning == {
        "enabled": True,
        "front_enabled": True,
        "end_enabled": True,
        "whitespace_enabled": True,
        "similarity_enabled": True,
    }


def test_response_pruning_enabled_false_skips_all_stages() -> None:
    pruner = Pruner.from_rules(
        {
            "front": {"prefix": ["got it"], "cut_mode": "sentence"},
            "end": {"prefix": ["let me know"], "cut_mode": "paragraph_to_end"},
        },
        config=PrunerConfig(
            response_pruning={
                "enabled": False,
            }
        ),
    )

    text = "**Got it.** Keep   this.\n\nLet me know if you want more examples."
    result = pruner.prune(text)

    assert result.pruned_text == text
    assert result.changed is False


def test_response_pruning_front_toggle_is_enforced() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["got it"], "cut_mode": "sentence"}},
        config=PrunerConfig(
            whitespace_mode="off",
            response_pruning={
                "front_enabled": False,
            },
        ),
    )

    result = pruner.prune("Got it. Keep this.")
    assert result.pruned_text == "Got it. Keep this."


def test_response_pruning_whitespace_toggle_is_enforced() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["not a match"], "cut_mode": "sentence"}},
        config=PrunerConfig(
            whitespace_mode="compact_prose",
            response_pruning={
                "whitespace_enabled": False,
            },
        ),
    )

    text = "Keep   this.\n\n\nAnd this."
    result = pruner.prune(text)
    assert result.pruned_text == text


def test_response_pruning_rejects_unknown_or_non_bool_fields() -> None:
    with pytest.raises(PrunerConfigError):
        PrunerConfig(response_pruning={"unknown": True})

    with pytest.raises(PrunerConfigError):
        invalid_config = cast(dict[str, bool], {"enabled": "yes"})
        PrunerConfig(response_pruning=invalid_config)


def test_prune_similar_sentences_drops_later_duplicate_sentence() -> None:
    text = (
        "The tagger should return structured spans. "
        "The tagger should return structured spans. "
        "The code validates the ranges."
    )

    assert prune_similar_sentences(text) == (
        "The tagger should return structured spans. The code validates the ranges."
    )


def test_prune_similar_sentences_preserves_code_blocks() -> None:
    text = (
        "The tagger should return structured spans.\n"
        "```python\n"
        "The tagger should return structured spans.\n"
        "```\n"
        "The tagger should return structured spans."
    )

    assert prune_similar_sentences(text) == (
        "The tagger should return structured spans.\n"
        "```python\n"
        "The tagger should return structured spans.\n"
        "```\n"
    )


def test_prune_similar_sentences_preserves_protected_sentences() -> None:
    text = (
        "Set max_keep to 12. "
        "Set max_keep to 12. "
        "FR-1.0.1 The library shall preserve this requirement. "
        "FR-1.0.1 The library shall preserve this requirement."
    )

    assert prune_similar_sentences(text) == text


def test_prune_similar_sentences_returns_text_without_sentence_spans() -> None:
    # Non-empty text with no terminal punctuation produces no sentence spans, so
    # the input is returned unchanged.
    text = "no terminal punctuation so no sentence spans"
    assert prune_similar_sentences(text) == text


def test_pruner_similarity_stage_runs_after_whitespace() -> None:
    pruner = Pruner.from_rules({"front": {"prefix": ["not a match"], "cut_mode": "sentence"}})
    text = (
        "The tagger   should return structured spans.\n\n"
        "The tagger should return structured spans."
    )

    result = pruner.prune(text)

    assert result.pruned_text == "The tagger should return structured spans."
    assert result.changed is True


def test_response_pruning_similarity_toggle_is_enforced() -> None:
    pruner = Pruner.from_rules(
        {"front": {"prefix": ["not a match"], "cut_mode": "sentence"}},
        config=PrunerConfig(response_pruning={"similarity_enabled": False}),
    )
    text = "The tagger should return structured spans. The tagger should return structured spans."

    result = pruner.prune(text)

    assert result.pruned_text == text


def test_pruner_config_rejects_invalid_similarity_threshold() -> None:
    with pytest.raises(PrunerConfigError):
        PrunerConfig(similarity_threshold=-1)

    with pytest.raises(PrunerConfigError):
        PrunerConfig(similarity_threshold=101)
