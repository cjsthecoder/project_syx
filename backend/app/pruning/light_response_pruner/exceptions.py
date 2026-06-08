"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Exception hierarchy for the light response pruner.

Defines the base PrunerError and specific errors raised for invalid rule
configuration, runtime configuration, and prune input.
"""


class PrunerError(Exception):
    """Base exception for all light-response-pruner errors.

    Catching this type captures every error the pruner raises. Concrete
    subclasses also inherit :class:`ValueError` so existing value-error handlers
    continue to work.
    """


class RuleConfigError(PrunerError, ValueError):
    """Raised when pruning rules cannot be loaded, parsed, or merged.

    Signals a problem with the rule *source* (file/mapping), as distinct from
    runtime tuning handled by :class:`PrunerConfigError`.
    """


class PrunerConfigError(PrunerError, ValueError):
    """Raised when runtime pruner configuration is invalid.

    Signals out-of-range or wrong-typed :class:`PrunerConfig` values (sizes,
    thresholds, whitespace mode, or unknown per-stage flags).
    """


class PrunerInputError(PrunerError, ValueError):
    """Raised when the text passed to ``prune`` violates configured constraints.

    For example, input that exceeds the configured maximum response size.
    """
