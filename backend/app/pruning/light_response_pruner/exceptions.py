"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
from __future__ import annotations


class PrunerError(Exception):
    """Base exception for all library-defined errors."""


class RuleConfigError(PrunerError, ValueError):
    """Raised when pruning rules cannot be loaded or merged."""


class PrunerConfigError(PrunerError, ValueError):
    """Raised when runtime pruner configuration is invalid."""


class PrunerInputError(PrunerError, ValueError):
    """Raised when prune input is invalid for configured constraints."""
