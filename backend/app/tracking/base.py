"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Base instrumentation interfaces and timestamp helpers for tracking.

Defines the Instrumentation protocol, a no-op implementation used when tracking
is disabled, and shared timestamp utilities plus the active-turn context var.
"""
import contextvars
from datetime import datetime, timezone
from typing import Optional, Protocol

_ACTIVE_TURN_ID: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "instrumentation_active_turn_id",
    default=None,
)


def utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def local_timestamp_compact() -> str:
    """Return a compact local timestamp (``YYYYMMDD_HHMMSS``)."""
    # Match logger file timestamp format in utils/logging.py
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class Instrumentation(Protocol):
    """Common interface used by application code."""

    def start_run(self, config: Optional[dict] = None) -> str:
        """Begin a run and return its run id."""
        ...

    def end_run(self, summary: Optional[dict] = None) -> None:
        """Finalize the active run with an optional summary."""
        ...

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        """Mark the start of a conversation turn."""
        ...

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        """Mark the end of the active turn and persist its rollup."""
        ...

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str:
        """Begin a model invocation and return its invocation id."""
        ...

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None:
        """Finalize an invocation with usage and timing data."""
        ...

    def record_stage(self, name: str, data: dict) -> None:
        """Record a named pipeline stage for the active turn."""
        ...


class NoopInstrumentation:
    """No-op implementation used when instrumentation is disabled."""

    def start_run(self, config: Optional[dict] = None) -> str:
        _ = config
        return ""

    def end_run(self, summary: Optional[dict] = None) -> None:
        _ = summary

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        _ = (turn_id, user_meta)
        _ACTIVE_TURN_ID.set(int(turn_id))

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        _ = output_meta
        _ACTIVE_TURN_ID.set(None)

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str:
        _ = (purpose, model, meta)
        return ""

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None:
        _ = (invocation_id, usage, timing)

    def record_stage(self, name: str, data: dict) -> None:
        _ = (name, data)
