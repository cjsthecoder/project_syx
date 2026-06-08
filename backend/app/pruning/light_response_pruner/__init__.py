"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Package initializer for the light_response_pruner subpackage.

Re-exports the public pruning API (Pruner, configuration loaders, models,
exceptions, and text helpers) for response post-processing.
"""
import logging

from .config import (
    RuleConfigError,
    export_rules_schema,
    load_rule_file,
    load_rules,
    merge_rules,
    validate_rules,
)
from .exceptions import PrunerConfigError, PrunerError, PrunerInputError
from .markdown import strip_markdown_markup
from .models import EndRuleSection, FrontRuleSection, PruneResult, PruneRules
from .normalize import normalize_for_prefix_match
from .pruner import Pruner, PrunerConfig, prune_response
from .similarity import prune_similar_sentences
from .whitespace import compact_whitespace

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "EndRuleSection",
    "FrontRuleSection",
    "Pruner",
    "PrunerConfig",
    "PrunerConfigError",
    "PrunerError",
    "PrunerInputError",
    "PruneResult",
    "PruneRules",
    "RuleConfigError",
    "export_rules_schema",
    "load_rule_file",
    "load_rules",
    "merge_rules",
    "normalize_for_prefix_match",
    "prune_response",
    "prune_similar_sentences",
    "strip_markdown_markup",
    "validate_rules",
    "compact_whitespace",
]
