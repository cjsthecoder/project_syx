"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
