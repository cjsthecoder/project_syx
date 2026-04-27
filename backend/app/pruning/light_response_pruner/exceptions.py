from __future__ import annotations


class PrunerError(Exception):
    """Base exception for all library-defined errors."""


class RuleConfigError(PrunerError, ValueError):
    """Raised when pruning rules cannot be loaded or merged."""


class PrunerConfigError(PrunerError, ValueError):
    """Raised when runtime pruner configuration is invalid."""


class PrunerInputError(PrunerError, ValueError):
    """Raised when prune input is invalid for configured constraints."""
