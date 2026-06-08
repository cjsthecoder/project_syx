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
    """Telemetry boundary for recording runs, turns, and model invocations.

    Application code depends on this protocol rather than a concrete backend so
    instrumentation can be swapped (file-backed) or disabled (no-op) without
    changing call sites. Implementations track the active run/turn/invocation
    and persist stage and usage data.
    """

    def start_run(self, config: Optional[dict] = None) -> str:
        """Begin a run and return its run id.

        Args:
            config: Optional configuration snapshot to record for the run.

        Returns:
            The new run id, or an empty string when a run cannot be started.
        """
        ...

    def end_run(self, summary: Optional[dict] = None) -> None:
        """Finalize the active run with an optional summary.

        Args:
            summary: Optional run-level summary to persist.
        """
        ...

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        """Mark the start of a conversation turn.

        Args:
            turn_id: Monotonically increasing turn identifier.
            user_meta: Optional per-turn metadata (e.g. ``project_id``).
        """
        ...

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        """Mark the end of the active turn and persist its rollup.

        Args:
            output_meta: Optional per-turn outputs merged into the turn rollup.
        """
        ...

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str:
        """Begin a model invocation and return its invocation id.

        Args:
            purpose: Invocation purpose (e.g. ``main`` or a mini purpose).
            model: Model identifier being invoked.
            meta: Optional invocation metadata (e.g. ``streaming``).

        Returns:
            The new invocation id, or an empty string when no run is active.
        """
        ...

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None:
        """Finalize an invocation with usage and timing data.

        Args:
            invocation_id: Id returned by :meth:`start_invocation`.
            usage: Optional reported token usage and source metadata.
            timing: Optional latency timing (e.g. ``ttlt_ms``, ``ttfb_ms``).
        """
        ...

    def record_stage(self, name: str, data: dict) -> None:
        """Record a named pipeline stage for the active turn.

        Args:
            name: Stage name.
            data: Stage payload to persist.
        """
        ...


class NoopInstrumentation:
    """No-op ``Instrumentation`` used when telemetry is disabled.

    Every method is a safe no-op except turn bookkeeping, which still tracks the
    active turn id in a context variable so downstream logging stays correct.
    """

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
