"""
Instrumentation facade (Option B strategy pattern).

Main code calls a shared Instrumentation instance directly.
Enabled/disabled behavior is centralized here via Noop vs Real implementations.
"""

from __future__ import annotations

import atexit
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def record_maintenance(self, job_type: str, meta: dict) -> None: ...


class NoopInstrumentation:
    """No-op implementation used when instrumentation is disabled."""

    def start_run(self, config: Optional[dict] = None) -> str:
        _ = config
        return ""

    def end_run(self, summary: Optional[dict] = None) -> None:
        _ = summary

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        _ = (turn_id, user_meta)

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        _ = output_meta

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

    def record_maintenance(self, job_type: str, meta: dict) -> None:
        _ = (job_type, meta)


class RealInstrumentation:
    """Minimal file-backed instrumentation implementation for lifecycle scaffolding."""

    def __init__(self, *, runs_dir: str, mode: str, run_id_override: Optional[str] = None):
        self.runs_dir = runs_dir or "runs"
        self.mode = (mode or "metrics").strip().lower()
        self.run_id_override = run_id_override.strip() if isinstance(run_id_override, str) and run_id_override.strip() else None
        self.run_id: Optional[str] = None
        self.run_dir: Optional[str] = None
        self._run_meta: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def _ensure_dir(self) -> None:
        os.makedirs(self.runs_dir, exist_ok=True)

    def _new_run_id(self) -> str:
        if self.run_id_override:
            return self.run_id_override
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"run_{ts}_{uuid.uuid4().hex[:8]}"

    def _append_jsonl(self, name: str, payload: Dict[str, Any]) -> None:
        if not self.run_dir:
            return
        path = os.path.join(self.run_dir, name)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _write_run_json(self) -> None:
        if not self.run_dir:
            return
        path = os.path.join(self.run_dir, "run.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self._run_meta, f, ensure_ascii=False, indent=2)

    def start_run(self, config: Optional[dict] = None) -> str:
        with self._lock:
            if self.run_id and self.run_dir:
                return self.run_id

            self._ensure_dir()
            self.run_id = self._new_run_id()
            self.run_dir = os.path.join(self.runs_dir, self.run_id)
            os.makedirs(self.run_dir, exist_ok=True)

            self._run_meta = {
                "run_id": self.run_id,
                "mode": self.mode,
                "started_at": _utc_iso(),
                "ended_at": None,
                "config": config or {},
                "summary": {},
            }
            self._write_run_json()

            # Ensure canonical files exist from run start.
            for fname in ("turns.jsonl", "invocations.jsonl", "maintenance.jsonl"):
                self._append_jsonl(fname, {})
            # Remove placeholder rows and keep empty files.
            for fname in ("turns.jsonl", "invocations.jsonl", "maintenance.jsonl"):
                path = os.path.join(self.run_dir, fname)
                with open(path, "w", encoding="utf-8", newline="\n"):
                    pass

            return self.run_id

    def end_run(self, summary: Optional[dict] = None) -> None:
        with self._lock:
            if not self.run_id:
                return
            self._run_meta["ended_at"] = _utc_iso()
            self._run_meta["summary"] = summary or {}
            self._write_run_json()

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        payload = {
            "ts": _utc_iso(),
            "event": "start_turn",
            "turn_id": int(turn_id),
            "user_meta": user_meta or {},
        }
        with self._lock:
            self._append_jsonl("turns.jsonl", payload)

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        payload = {
            "ts": _utc_iso(),
            "event": "end_turn",
            "output_meta": output_meta or {},
        }
        with self._lock:
            self._append_jsonl("turns.jsonl", payload)

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str:
        invocation_id = uuid.uuid4().hex
        payload = {
            "ts": _utc_iso(),
            "event": "start_invocation",
            "invocation_id": invocation_id,
            "purpose": purpose,
            "model": model,
            "meta": meta or {},
        }
        with self._lock:
            self._append_jsonl("invocations.jsonl", payload)
        return invocation_id

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None:
        payload = {
            "ts": _utc_iso(),
            "event": "end_invocation",
            "invocation_id": invocation_id,
            "usage": usage or {},
            "timing": timing or {},
        }
        with self._lock:
            self._append_jsonl("invocations.jsonl", payload)

    def record_stage(self, name: str, data: dict) -> None:
        payload = {
            "ts": _utc_iso(),
            "event": "stage",
            "name": name,
            "data": data or {},
        }
        with self._lock:
            self._append_jsonl("turns.jsonl", payload)

    def record_maintenance(self, job_type: str, meta: dict) -> None:
        payload = {
            "ts": _utc_iso(),
            "event": "maintenance",
            "job_type": job_type,
            "meta": meta or {},
        }
        with self._lock:
            self._append_jsonl("maintenance.jsonl", payload)


_INSTRUMENTATION: Instrumentation = NoopInstrumentation()
_REGISTERED_ATEXIT = False
_INIT_LOCK = threading.RLock()


def get_instrumentation() -> Instrumentation:
    return _INSTRUMENTATION


def init_instrumentation(settings: Any) -> Instrumentation:
    """Initialize global instrumentation singleton from app settings."""
    global _INSTRUMENTATION, _REGISTERED_ATEXIT
    with _INIT_LOCK:
        enabled = bool(getattr(settings, "instrumentation_enabled", False))
        if not enabled:
            _INSTRUMENTATION = NoopInstrumentation()
            return _INSTRUMENTATION

        mode = str(getattr(settings, "instrumentation_mode", "metrics") or "metrics")
        runs_dir = str(getattr(settings, "instrumentation_runs_dir", "runs") or "runs")
        run_id = getattr(settings, "instrumentation_run_id", None)

        real = RealInstrumentation(runs_dir=runs_dir, mode=mode, run_id_override=run_id)
        _INSTRUMENTATION = real

        if not _REGISTERED_ATEXIT:
            def _flush_on_exit() -> None:
                try:
                    get_instrumentation().end_run({"reason": "atexit"})
                except Exception:
                    pass
            atexit.register(_flush_on_exit)
            _REGISTERED_ATEXIT = True

        return _INSTRUMENTATION

