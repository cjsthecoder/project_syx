from __future__ import annotations

from app.pruning.light_response_pruner import (
    EndRuleSection,
    FrontRuleSection,
    Pruner,
    PrunerConfig,
    PrunerConfigError,
    PrunerError,
    PruneResult,
    PrunerInputError,
    PruneRules,
    RuleConfigError,
    compact_whitespace,
    export_rules_schema,
    load_rule_file,
    load_rules,
    merge_rules,
    normalize_for_prefix_match,
    prune_response,
    prune_similar_sentences,
    strip_markdown_markup,
    validate_rules,
)


def test_public_api_exports_are_importable() -> None:
    assert FrontRuleSection is not None
    assert EndRuleSection is not None
    assert Pruner is not None
    assert PrunerConfig is not None
    assert PrunerError is not None
    assert PrunerConfigError is not None
    assert PrunerInputError is not None
    assert PruneRules is not None
    assert PruneResult is not None
    assert RuleConfigError is not None
    assert validate_rules is not None
    assert load_rule_file is not None
    assert load_rules is not None
    assert merge_rules is not None
    assert export_rules_schema is not None
    assert normalize_for_prefix_match is not None
    assert prune_response is not None
    assert prune_similar_sentences is not None
    assert compact_whitespace is not None
    assert strip_markdown_markup is not None
