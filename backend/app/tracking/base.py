from __future__ import annotations

import contextvars
from datetime import datetime, timezone
from typing import Optional, Protocol

_ACTIVE_TURN_ID: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "instrumentation_active_turn_id",
    default=None,
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_timestamp_compact() -> str:
    # Match logger file timestamp format in utils/logging.py
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class Instrumentation(Protocol):
    """Common interface used by application code."""

    def start_run(self, config: Optional[dict] = None) -> str: ...

    def end_run(self, summary: Optional[dict] = None) -> None: ...

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None: ...

    def end_turn(self, output_meta: Optional[dict] = None) -> None: ...

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str: ...

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None: ...

    def record_stage(self, name: str, data: dict) -> None: ...


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
