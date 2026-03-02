"""
Instrumentation facade (Option B strategy pattern).

Main code calls a shared Instrumentation instance directly.
Enabled/disabled behavior is centralized here via Noop vs Real implementations.
"""

from __future__ import annotations

import atexit
import contextvars
import json
import logging
import time
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)
_ACTIVE_TURN_ID: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "instrumentation_active_turn_id",
    default=None,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_timestamp_compact() -> str:
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
        self._ended = False
        self._invocation_seq = 0
        self._turn_state: Dict[int, Dict[str, Any]] = {}
        self._invocation_state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _as_int(v: Any, default: Optional[int] = 0) -> Optional[int]:
        try:
            if v is None:
                return int(default) if default is not None else None
            return int(v)
        except Exception:
            return int(default) if default is not None else None

    @staticmethod
    def _normalize_ms(value: Any, *, field: str, invocation_id: str) -> int:
        try:
            ms = int(value)
        except Exception:
            logger.warning("tracking.%s missing/invalid for invocation_id=%s; forcing 0", field, invocation_id)
            return 0
        if ms < 0:
            logger.warning("tracking.%s negative for invocation_id=%s; forcing 0", field, invocation_id)
            return 0
        return int(ms)

    def _ensure_dir(self) -> None:
        os.makedirs(self.runs_dir, exist_ok=True)

    def _new_run_id(self) -> str:
        ts = _local_timestamp_compact()
        if self.run_id_override:
            return f"{self.run_id_override}_{ts}"
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
            try:
                if self.run_id and self.run_dir:
                    logger.error("tracking.start_run called more than once; ignoring duplicate call.")
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
            except Exception as e:
                logger.warning("tracking.start_run failed: %s", e, exc_info=True)
                return ""

    def end_run(self, summary: Optional[dict] = None) -> None:
        with self._lock:
            try:
                if not self.run_id:
                    logger.error("tracking.end_run called before start_run; ignoring.")
                    return
                if self._ended:
                    logger.error("tracking.end_run called more than once; ignoring duplicate call.")
                    return
                self._run_meta["ended_at"] = _utc_iso()
                self._run_meta["summary"] = summary or {}
                self._write_run_json()
                self._ended = True
            except Exception as e:
                logger.warning("tracking.end_run failed: %s", e, exc_info=True)

    def start_turn(self, turn_id: int, user_meta: Optional[dict] = None) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                tid = int(turn_id)
                _ACTIVE_TURN_ID.set(tid)
                self._turn_state[tid] = {
                    "_turn_started_monotonic": time.perf_counter(),
                    "prompt_system_tokens_est": 0,
                    "prompt_history_tokens_est": 0,
                    "prompt_rag_tokens_est": 0,
                    "prompt_profile_tokens_est": 0,
                    "prompt_other_tokens_est": 0,
                    "main_total_tokens_reported": 0,
                    "mini_total_tokens_reported_sum": 0,
                    "ttfb_ms_main": 0,
                    "ttlt_ms_main": 0,
                    "_has_main_latency": False,
                    "route": "OTHER",
                    "rag_enabled": False,
                    "retrieved_count": 0,
                    "kept_count": 0,
                    "expanded_unique_chunks_after_merge": 0,
                }
                payload = {
                    "ts": _utc_iso(),
                    "event": "start_turn",
                    "turn_id": tid,
                    "user_meta": user_meta or {},
                }
                self._append_jsonl("turns.jsonl", payload)
            except Exception as e:
                logger.warning("tracking.start_turn failed: %s", e, exc_info=True)

    def end_turn(self, output_meta: Optional[dict] = None) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                tid = _ACTIVE_TURN_ID.get()
                if tid is None and isinstance(output_meta, dict):
                    tid = self._as_int(output_meta.get("turn_id"), None)  # type: ignore[arg-type]
                turn_rollup = self._turn_state.get(int(tid)) if tid is not None else None
                main_total = int((turn_rollup or {}).get("main_total_tokens_reported", 0))
                mini_total = int((turn_rollup or {}).get("mini_total_tokens_reported_sum", 0))
                ttfb_main = int((turn_rollup or {}).get("ttfb_ms_main", 0))
                ttlt_main = int((turn_rollup or {}).get("ttlt_ms_main", 0))
                has_main_latency = bool((turn_rollup or {}).get("_has_main_latency", False))
                if not has_main_latency:
                    logger.warning(
                        "tracking.turn missing main latency turn_id=%s; forcing 0 values",
                        str(tid),
                    )
                out = output_meta or {}
                prompt_system = int((turn_rollup or {}).get("prompt_system_tokens_est", 0))
                prompt_history = int((turn_rollup or {}).get("prompt_history_tokens_est", 0))
                prompt_rag = int((turn_rollup or {}).get("prompt_rag_tokens_est", 0))
                prompt_profile = int((turn_rollup or {}).get("prompt_profile_tokens_est", 0))
                prompt_other = int((turn_rollup or {}).get("prompt_other_tokens_est", 0))
                route = str((out or {}).get("route") or (turn_rollup or {}).get("route") or "OTHER")
                rag_enabled = bool((out or {}).get("rag_enabled", (turn_rollup or {}).get("rag_enabled", False)))
                retrieved_count = int((out or {}).get("retrieved_count", (turn_rollup or {}).get("retrieved_count", 0)) or 0)
                kept_count = int((out or {}).get("kept_count", (turn_rollup or {}).get("kept_count", 0)) or 0)
                expanded_unique_chunks_after_merge = int(
                    (out or {}).get(
                        "expanded_unique_chunks_after_merge",
                        (turn_rollup or {}).get("expanded_unique_chunks_after_merge", 0),
                    )
                    or 0
                )
                rag_tokens_injected_est = int((out or {}).get("rag_tokens_injected_est", prompt_rag) or 0)
                final_context_tokens_est = int(
                    (out or {}).get(
                        "final_context_tokens_est",
                        prompt_system + prompt_history + prompt_rag + prompt_profile + prompt_other,
                    )
                    or 0
                )
                final_context_clipped = bool((out or {}).get("final_context_clipped", False))
                turn_started_mono = (turn_rollup or {}).get("_turn_started_monotonic", None)
                ttlt_turn_total = 0
                try:
                    if turn_started_mono is not None:
                        ttlt_turn_total = max(0, int((time.perf_counter() - float(turn_started_mono)) * 1000.0))
                except Exception:
                    ttlt_turn_total = 0
                payload = {
                    "ts": _utc_iso(),
                    "event": "end_turn",
                    "turn_id": int(tid) if tid is not None else None,
                    "prompt_system_tokens_est": int(prompt_system),
                    "prompt_history_tokens_est": int(prompt_history),
                    "prompt_rag_tokens_est": int(prompt_rag),
                    "prompt_profile_tokens_est": int(prompt_profile),
                    "prompt_other_tokens_est": int(prompt_other),
                    "route": route,
                    "rag_enabled": bool(rag_enabled),
                    "retrieved_count": int(retrieved_count),
                    "kept_count": int(kept_count),
                    "expanded_unique_chunks_after_merge": int(expanded_unique_chunks_after_merge),
                    "rag_tokens_injected_est": int(rag_tokens_injected_est),
                    "final_context_tokens_est": int(final_context_tokens_est),
                    "final_context_clipped": bool(final_context_clipped),
                    "main_total_tokens_reported": main_total,
                    "mini_total_tokens_reported_sum": mini_total,
                    "turn_total_tokens_reported": int(main_total + mini_total),
                    "ttfb_ms_main": int(ttfb_main),
                    "ttlt_ms_main": int(ttlt_main),
                    "ttlt_ms_turn_total": int(ttlt_turn_total),
                    "output_meta": output_meta or {},
                }
                self._append_jsonl("turns.jsonl", payload)
                _ACTIVE_TURN_ID.set(None)
                if tid is not None:
                    self._turn_state.pop(int(tid), None)
            except Exception as e:
                logger.warning("tracking.end_turn failed: %s", e, exc_info=True)

    def start_invocation(self, purpose: str, model: str, meta: Optional[dict] = None) -> str:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return ""
                self._invocation_seq += 1
                # Unique within a run by construction (monotonic sequence).
                invocation_id = f"inv_{self._invocation_seq:08d}"
                start_ts = _utc_iso()
                turn_id = _ACTIVE_TURN_ID.get()
                self._invocation_state[invocation_id] = {
                    "turn_id": int(turn_id) if turn_id is not None else None,
                    "purpose": purpose,
                    "model": model,
                    "meta": meta or {},
                    "start_ts": start_ts,
                }
                payload = {
                    "ts": start_ts,
                    "event": "start_invocation",
                    "invocation_id": invocation_id,
                    "turn_id": turn_id,
                    "purpose": purpose,
                    "model": model,
                    "meta": meta or {},
                }
                self._append_jsonl("invocations.jsonl", payload)
                return invocation_id
            except Exception as e:
                logger.warning("tracking.start_invocation failed: %s", e, exc_info=True)
                return ""

    def end_invocation(
        self,
        invocation_id: str,
        usage: Optional[dict] = None,
        timing: Optional[dict] = None,
    ) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                state = self._invocation_state.pop(invocation_id, {})
                turn_id = state.get("turn_id")
                purpose = str((usage or {}).get("purpose") or state.get("purpose") or "other")
                model = str((usage or {}).get("model") or state.get("model") or "")
                streaming = bool((state.get("meta") or {}).get("streaming", False)) if isinstance(state.get("meta"), dict) else False
                prompt_tok = self._as_int((usage or {}).get("prompt_tokens_reported"), 0)
                completion_tok = self._as_int((usage or {}).get("completion_tokens_reported"), 0)
                total_tok = self._as_int((usage or {}).get("total_tokens_reported"), prompt_tok + completion_tok)
                usage_is_estimate = bool((usage or {}).get("usage_is_estimate", True))
                if total_tok <= 0:
                    total_tok = int(prompt_tok + completion_tok)

                # Keep canonical fields stable and permit optional extra usage fields in meta diagnostics.
                meta_diag: Dict[str, Any] = {}
                if isinstance(state.get("meta"), dict):
                    meta_diag.update(state.get("meta", {}))
                extra_usage = (usage or {}).get("extra_usage")
                if isinstance(extra_usage, dict):
                    meta_diag["extra_usage"] = extra_usage

                end_ts = _utc_iso()
                ttlt_ms = self._normalize_ms((timing or {}).get("ttlt_ms"), field="ttlt_ms", invocation_id=invocation_id)
                first_token_ts = (timing or {}).get("first_token_ts")
                if streaming:
                    ttfb_ms = self._normalize_ms((timing or {}).get("ttfb_ms"), field="ttfb_ms", invocation_id=invocation_id)
                    if ttfb_ms == 0:
                        logger.warning(
                            "tracking.streaming invocation had no yielded token timing invocation_id=%s; ttfb_ms forced to 0",
                            invocation_id,
                        )
                    if not first_token_ts:
                        first_token_ts = None
                else:
                    # Non-streaming: first token is effectively available at completion.
                    first_token_ts = end_ts
                    ttfb_ms = int(ttlt_ms)

                # 5.5.2 rollups: main contributes to main_total, non-main contributes to mini_total.
                if isinstance(turn_id, int):
                    ts = self._turn_state.setdefault(
                        int(turn_id),
                        {
                            "prompt_system_tokens_est": 0,
                            "prompt_history_tokens_est": 0,
                            "prompt_rag_tokens_est": 0,
                            "prompt_profile_tokens_est": 0,
                            "prompt_other_tokens_est": 0,
                            "main_total_tokens_reported": 0,
                            "mini_total_tokens_reported_sum": 0,
                            "route": "OTHER",
                            "rag_enabled": False,
                            "retrieved_count": 0,
                            "kept_count": 0,
                            "expanded_unique_chunks_after_merge": 0,
                        },
                    )
                    if purpose == "main":
                        ts["main_total_tokens_reported"] = int(ts.get("main_total_tokens_reported", 0)) + int(total_tok)
                        ts["ttfb_ms_main"] = int(ttfb_ms)
                        ts["ttlt_ms_main"] = int(ttlt_ms)
                        ts["_has_main_latency"] = True
                    else:
                        ts["mini_total_tokens_reported_sum"] = int(ts.get("mini_total_tokens_reported_sum", 0)) + int(total_tok)

                payload = {
                    "ts": _utc_iso(),
                    "event": "end_invocation",
                    "invocation_id": invocation_id,
                    "turn_id": turn_id,
                    "purpose": purpose,
                    "model": model,
                    "prompt_tokens_reported": int(prompt_tok),
                    "completion_tokens_reported": int(completion_tok),
                    "total_tokens_reported": int(total_tok),
                    "usage_is_estimate": bool(usage_is_estimate),
                    "meta": meta_diag,
                    "timing": {
                        "ttfb_ms": int(ttfb_ms),
                        "ttlt_ms": int(ttlt_ms),
                    },
                    "start_ts": state.get("start_ts"),
                    "end_ts": end_ts,
                    "first_token_ts": first_token_ts,
                    "ttfb_ms": int(ttfb_ms),
                    "ttlt_ms": int(ttlt_ms),
                }
                self._append_jsonl("invocations.jsonl", payload)
            except Exception as e:
                logger.warning("tracking.end_invocation failed: %s", e, exc_info=True)

    def record_stage(self, name: str, data: dict) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                tid = _ACTIVE_TURN_ID.get()
                if isinstance(tid, int) and str(name) == "prompt_assembly":
                    ts = self._turn_state.setdefault(
                        int(tid),
                        {
                            "prompt_system_tokens_est": 0,
                            "prompt_history_tokens_est": 0,
                            "prompt_rag_tokens_est": 0,
                            "prompt_profile_tokens_est": 0,
                            "prompt_other_tokens_est": 0,
                            "main_total_tokens_reported": 0,
                            "mini_total_tokens_reported_sum": 0,
                            "route": "OTHER",
                            "rag_enabled": False,
                            "retrieved_count": 0,
                            "kept_count": 0,
                            "expanded_unique_chunks_after_merge": 0,
                        },
                    )
                    ts["prompt_system_tokens_est"] = self._as_int((data or {}).get("prompt_system_tokens_est"), 0)
                    ts["prompt_history_tokens_est"] = self._as_int((data or {}).get("prompt_history_tokens_est"), 0)
                    ts["prompt_rag_tokens_est"] = self._as_int((data or {}).get("prompt_rag_tokens_est"), 0)
                    ts["prompt_profile_tokens_est"] = self._as_int((data or {}).get("prompt_profile_tokens_est"), 0)
                    ts["prompt_other_tokens_est"] = self._as_int((data or {}).get("prompt_other_tokens_est"), 0)
                if isinstance(tid, int) and str(name) == "retrieval_selection_expansion":
                    ts = self._turn_state.setdefault(
                        int(tid),
                        {
                            "prompt_system_tokens_est": 0,
                            "prompt_history_tokens_est": 0,
                            "prompt_rag_tokens_est": 0,
                            "prompt_profile_tokens_est": 0,
                            "prompt_other_tokens_est": 0,
                            "main_total_tokens_reported": 0,
                            "mini_total_tokens_reported_sum": 0,
                            "route": "OTHER",
                            "rag_enabled": False,
                            "retrieved_count": 0,
                            "kept_count": 0,
                            "expanded_unique_chunks_after_merge": 0,
                        },
                    )
                    ts["route"] = str((data or {}).get("route") or ts.get("route") or "OTHER")
                    ts["rag_enabled"] = True
                    ts["retrieved_count"] = self._as_int((data or {}).get("ordered_candidates"), 0)
                    ts["kept_count"] = self._as_int((data or {}).get("selected_candidates"), 0)
                    ts["expanded_unique_chunks_after_merge"] = self._as_int(
                        (data or {}).get("expanded_unique_chunks_after_merge"),
                        self._as_int((data or {}).get("kept_candidates"), 0),
                    )
                payload = {
                    "ts": _utc_iso(),
                    "event": "stage",
                    "name": name,
                    "turn_id": int(tid) if isinstance(tid, int) else None,
                    "data": data or {},
                }
                self._append_jsonl("turns.jsonl", payload)
            except Exception as e:
                logger.warning("tracking.record_stage failed: %s", e, exc_info=True)

    def record_maintenance(self, job_type: str, meta: dict) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                payload = {
                    "ts": _utc_iso(),
                    "event": "maintenance",
                    "job_type": job_type,
                    "meta": meta or {},
                }
                self._append_jsonl("maintenance.jsonl", payload)
            except Exception as e:
                logger.warning("tracking.record_maintenance failed: %s", e, exc_info=True)


_INSTRUMENTATION: Instrumentation = NoopInstrumentation()
_REGISTERED_ATEXIT = False
_INIT_LOCK = threading.RLock()


def get_instrumentation() -> Instrumentation:
    return _INSTRUMENTATION


def init_instrumentation(settings: Any, *, has_lifespan_hook: bool = False) -> Instrumentation:
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

        # Register process-exit fallback only when lifecycle hooks are unavailable.
        if (not has_lifespan_hook) and (not _REGISTERED_ATEXIT):
            def _flush_on_exit() -> None:
                try:
                    get_instrumentation().end_run({"reason": "atexit"})
                except Exception:
                    pass
            atexit.register(_flush_on_exit)
            _REGISTERED_ATEXIT = True

        return _INSTRUMENTATION

