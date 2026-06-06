"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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
