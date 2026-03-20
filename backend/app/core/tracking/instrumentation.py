"""
Instrumentation facade (Option B strategy pattern).

Main code calls a shared Instrumentation instance directly.
Enabled/disabled behavior is centralized here via Noop vs Real implementations.
"""

from __future__ import annotations

import atexit
import contextvars
import hashlib
import json
import logging
import time
import os
import subprocess
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


class RealInstrumentation:
    """Minimal file-backed instrumentation implementation for lifecycle scaffolding."""

    def __init__(
        self,
        *,
        runs_dir: str,
        mode: str,
        run_id_override: Optional[str] = None,
        prompt_tol_abs_tokens: int = 25,
        prompt_tol_pct: float = 0.02,
    ):
        self.runs_dir = runs_dir or "runs"
        self.mode = (mode or "metrics").strip().lower()
        self.run_id_override = run_id_override.strip() if isinstance(run_id_override, str) and run_id_override.strip() else None
        self.prompt_tol_abs_tokens = max(0, int(prompt_tol_abs_tokens))
        try:
            self.prompt_tol_pct = max(0.0, float(prompt_tol_pct))
        except Exception:
            self.prompt_tol_pct = 0.02
        self.run_id: Optional[str] = None
        self.run_dir: Optional[str] = None
        self._run_meta: Dict[str, Any] = {}
        self._ended = False
        self._invocation_seq = 0
        self._turn_state: Dict[int, Dict[str, Any]] = {}
        self._invocation_state: Dict[str, Dict[str, Any]] = {}
        self._models_observed: Dict[str, set] = {}
        self._last_turn_id: Optional[int] = None
        self._lock = threading.RLock()

    @staticmethod
    def _turn_state_defaults() -> Dict[str, Any]:
        return {
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
            "main_invocation_count": 0,
            "main_invocation_total_tokens_reported": 0,
            "main_prompt_tokens_reported": 0,
            "main_completion_tokens_reported": 0,
            "main_usage_is_estimate": True,
            "main_streaming": None,
            "interactive_non_main_total_tokens_reported": 0,
            "provider_tokens_total": 0,
            "estimated_tokens_total": 0,
            "zero_fallback_tokens_total": 0,
            "invocations_count_total": 0,
            "main_invocations_count": 0,
            "mini_invocations_count": 0,
        }

    @staticmethod
    def _as_int(v: Any, default: Optional[int] = 0) -> Optional[int]:
        try:
            if v is None:
                return int(default) if default is not None else None
            return int(v)
        except Exception:
            return int(default) if default is not None else None

    @staticmethod
    def _to_non_negative_int_or_none(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            ms = int(value)
            if ms < 0:
                return None
            return int(ms)
        except Exception:
            return None

    @staticmethod
    def _schema_error(
        *,
        code: str,
        field: str,
        expected: Any,
        actual: Any,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": str(code),
            "field": str(field),
            "expected": expected,
            "actual": actual,
        }
        if message:
            payload["message"] = str(message)
        if isinstance(details, dict) and details:
            payload["details"] = details
        return payload

    @staticmethod
    def _epoch_ms_from_iso(value: Any) -> Optional[int]:
        if not isinstance(value, str):
            return None
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000.0)
        except Exception:
            return None

    @staticmethod
    def _resolve_repo_root() -> str:
        # .../backend/app/core/tracking/instrumentation.py -> repo root
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

    @classmethod
    def _detect_git_metadata(cls) -> Dict[str, Any]:
        repo_root = cls._resolve_repo_root()
        git_commit = "unknown"
        git_dirty = False
        try:
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if rev.returncode == 0:
                parsed = str(rev.stdout or "").strip()
                if parsed:
                    git_commit = parsed
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if dirty.returncode == 0:
                git_dirty = bool(str(dirty.stdout or "").strip())
        except Exception:
            pass
        return {"git_commit": git_commit, "git_dirty": bool(git_dirty)}

    @classmethod
    def _normalize_config_snapshot(cls, cfg_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(cfg_snapshot or {})
        prompt_budgeting = out.get("prompt_budgeting")
        if isinstance(prompt_budgeting, dict):
            pb = dict(prompt_budgeting)
            requested = pb.get("max_output_tokens_requested")
            effective = pb.get("max_output_tokens_effective")
            legacy = pb.get("max_output_tokens")
            if requested is None and legacy is not None:
                requested = legacy
            if effective is None and requested is not None:
                effective = requested
            pb["max_output_tokens_requested"] = requested
            pb["max_output_tokens_effective"] = effective
            pb.pop("max_output_tokens", None)
            known = bool(
                pb.get("model_context_window_tokens") is not None
                and pb.get("max_output_tokens_requested") is not None
                and pb.get("max_output_tokens_effective") is not None
                and pb.get("target_max_prompt_tokens") is not None
                and pb.get("history_max_tokens") is not None
                and pb.get("rag_max_tokens") is not None
                and pb.get("profile_max_tokens") is not None
                and pb.get("system_max_tokens") is not None
            )
            pb["prompt_budgeting_known"] = bool(pb.get("prompt_budgeting_known", known))
            out["prompt_budgeting"] = pb
        elif "prompt_budgeting" not in out:
            out["prompt_budgeting"] = {
                "model_context_window_tokens": None,
                "max_output_tokens_requested": None,
                "max_output_tokens_effective": None,
                "target_max_prompt_tokens": None,
                "history_max_tokens": None,
                "rag_max_tokens": None,
                "profile_max_tokens": None,
                "system_max_tokens": None,
                "prompt_budgeting_known": False,
            }

        maintenance = out.get("maintenance")
        if isinstance(maintenance, dict):
            m = dict(maintenance)
            m.setdefault("reporting_scope", "sleep_only")
            out["maintenance"] = m
        else:
            out["maintenance"] = {"reporting_scope": "sleep_only"}

        if "git_commit" not in out or "git_dirty" not in out:
            out.update(cls._detect_git_metadata())
        else:
            out["git_commit"] = str(out.get("git_commit") or "unknown")
            out["git_dirty"] = bool(out.get("git_dirty"))
        return out

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

    @staticmethod
    def _snapshot_project_personality(project_id: str) -> Dict[str, Any]:
        pid = str(project_id or "").strip()
        out: Dict[str, Any] = {
            "as_run_personality": None,
            "as_run_personality_sha256": None,
            "personality_captured_at": None,
            "personality_source": "unavailable",
        }
        if not pid:
            return out
        personality_path = os.path.join("memory", pid, "personality.json")
        source = "project_file" if os.path.isfile(personality_path) else "default_fallback"
        try:
            # Local import avoids adding a hard runtime dependency at module import time.
            from ..personality import load_project_personality

            personality = load_project_personality(pid)
            if isinstance(personality, dict):
                canonical = json.loads(json.dumps(personality, ensure_ascii=False))
                digest_src = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                out["as_run_personality"] = canonical
                out["as_run_personality_sha256"] = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
                out["personality_captured_at"] = _utc_iso()
                out["personality_source"] = source
        except Exception as e:
            logger.warning("tracking.project_observed personality snapshot failed project_id=%s: %s", pid, e)
        return out

    def _observe_project_for_run(self, user_meta: Optional[dict]) -> None:
        if not isinstance(user_meta, dict):
            return
        project_id_raw = user_meta.get("project_id")
        project_id = str(project_id_raw or "").strip()
        if not project_id:
            return
        observed = self._run_meta.get("project_observed")
        if not isinstance(observed, dict):
            return
        changed = False
        seen = observed.get("projects_seen")
        if not isinstance(seen, list):
            seen = []
        if project_id not in seen:
            seen.append(project_id)
            observed["projects_seen"] = seen
            changed = True
        run_project_id = str(observed.get("project_id") or "").strip()
        if not run_project_id:
            observed["project_id"] = project_id
            observed.update(self._snapshot_project_personality(project_id))
            changed = True
        elif run_project_id != project_id:
            if not bool(observed.get("multi_project_run", False)):
                observed["multi_project_run"] = True
                changed = True
        if changed:
            self._run_meta["project_observed"] = observed
            self._write_run_json()

    def _record_benchmark_turn_result(
        self,
        *,
        turn_id: int,
        turn_payload: Dict[str, Any],
        output_meta: Dict[str, Any],
    ) -> None:
        # 5.11 benchmark artifact emission when instrumentation is enabled.
        if not self.run_id or not self.run_dir:
            return

        case_id = f"{self.run_id}:turn:{int(turn_id)}"
        prompt_text_raw = output_meta.get("prompt_text")
        response_text_raw = output_meta.get("response_text")
        model_id_raw = output_meta.get("model_id")
        model_id = str(model_id_raw).strip() if isinstance(model_id_raw, str) and model_id_raw.strip() else None

        prompt_text = str(prompt_text_raw) if isinstance(prompt_text_raw, str) else None
        response_text = str(response_text_raw) if isinstance(response_text_raw, str) else None
        missing_fields = []
        if not model_id:
            missing_fields.append("model_id")
        if prompt_text is None:
            missing_fields.append("prompt_text")
        if response_text is None:
            missing_fields.append("response_text")
        if turn_payload.get("main_total_tokens_reported") is None:
            missing_fields.append("main_total_tokens_reported")
        if turn_payload.get("turn_total_tokens_reported") is None:
            missing_fields.append("turn_total_tokens_reported")
        if turn_payload.get("ttlt_ms_turn_total") is None:
            missing_fields.append("latency_ms")

        record: Dict[str, Any] = {
            "case_id": case_id,
            "system": "morpheus",
            "model_id": model_id,
            "timestamp": turn_payload.get("ts"),
            "run_id": self.run_id,
            "turn_id": int(turn_id),
            "main_total_tokens_reported": turn_payload.get("main_total_tokens_reported"),
            "turn_total_tokens_reported": turn_payload.get("turn_total_tokens_reported"),
            "latency_ms": turn_payload.get("ttlt_ms_turn_total"),
            "metrics_source": "morpheus_instrumentation",
            "completeness": ("full" if not missing_fields else "partial"),
            "missing_fields": missing_fields,
            "prompt_text": prompt_text,
            "response_text": response_text,
            "scorer_output_id": None,
        }
        self._append_jsonl("benchmark_results.jsonl", record)

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
                self._models_observed = {}

                cfg_in = config or {}
                if isinstance(cfg_in, dict) and isinstance(cfg_in.get("config_snapshot"), dict):
                    cfg_snapshot = dict(cfg_in.get("config_snapshot") or {})
                elif isinstance(cfg_in, dict):
                    cfg_snapshot = dict(cfg_in)
                else:
                    cfg_snapshot = {}
                cfg_snapshot = self._normalize_config_snapshot(cfg_snapshot)

                self._run_meta = {
                    "run_id": self.run_id,
                    "mode": self.mode,
                    "started_at": _utc_iso(),
                    "ended_at": None,
                    # 5.10: immutable startup snapshot (authoritative)
                    "config_snapshot": cfg_snapshot,
                    # Runtime-observed values are not part of immutable snapshot.
                    "models_observed": {},
                    "project_observed": {
                        "project_id": None,
                        "projects_seen": [],
                        "multi_project_run": False,
                        "as_run_personality": None,
                        "as_run_personality_sha256": None,
                        "personality_captured_at": None,
                        "personality_source": "unavailable",
                    },
                    "summary": {},
                }
                self._write_run_json()

                # Ensure canonical files exist from run start.
                for fname in ("turns.jsonl",):
                    self._append_jsonl(fname, {})
                # Remove placeholder rows and keep empty files.
                for fname in ("turns.jsonl",):
                    path = os.path.join(self.run_dir, fname)
                    with open(path, "w", encoding="utf-8", newline="\n"):
                        pass
                for fname in ("benchmark_results.jsonl", "benchmark_scores.jsonl"):
                    self._append_jsonl(fname, {})
                for fname in ("benchmark_results.jsonl", "benchmark_scores.jsonl"):
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
                observed: Dict[str, Any] = {}
                for purpose, models in self._models_observed.items():
                    vals = sorted([str(m) for m in models if str(m).strip()])
                    if vals:
                        observed[str(purpose)] = vals
                self._run_meta["ended_at"] = _utc_iso()
                self._run_meta["models_observed"] = observed
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
                if self._last_turn_id is not None:
                    if tid == int(self._last_turn_id):
                        logger.warning("tracking.start_turn duplicate turn_id=%s for run_id=%s; skipping write", tid, self.run_id)
                        return
                    if tid < int(self._last_turn_id):
                        logger.warning(
                            "tracking.start_turn non-monotonic turn_id=%s (last=%s) run_id=%s; skipping write",
                            tid,
                            self._last_turn_id,
                            self.run_id,
                        )
                        return
                self._last_turn_id = int(tid)
                _ACTIVE_TURN_ID.set(tid)
                self._turn_state[tid] = {
                    "_turn_started_monotonic": time.perf_counter(),
                    "_turn_start_ts": _utc_iso(),
                    "ttfb_ms_main": None,
                    "ttlt_ms_main": None,
                    "_has_main_latency": False,
                    **self._turn_state_defaults(),
                }
                payload = {
                    "ts": _utc_iso(),
                    "event": "start_turn",
                    "run_id": self.run_id,
                    "turn_id": tid,
                    "user_meta": user_meta or {},
                }
                self._append_jsonl("turns.jsonl", payload)
                self._observe_project_for_run(user_meta)
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
                if tid is None:
                    logger.warning("tracking.end_turn missing turn_id; skipping write")
                    return
                turn_rollup = self._turn_state.get(int(tid))
                if not isinstance(turn_rollup, dict):
                    logger.warning("tracking.end_turn missing turn state turn_id=%s; skipping write", tid)
                    return
                main_total = int((turn_rollup or {}).get("main_total_tokens_reported", 0))
                mini_total = int((turn_rollup or {}).get("mini_total_tokens_reported_sum", 0))
                ttfb_main_raw = (turn_rollup or {}).get("ttfb_ms_main", None)
                ttlt_main_raw = (turn_rollup or {}).get("ttlt_ms_main", None)
                ttfb_main = self._to_non_negative_int_or_none(ttfb_main_raw)
                ttlt_main = self._to_non_negative_int_or_none(ttlt_main_raw)
                has_main_latency = bool((turn_rollup or {}).get("_has_main_latency", False))
                main_streaming = bool((turn_rollup or {}).get("main_streaming", False))
                if int((turn_rollup or {}).get("main_invocation_count", 0)) == 0:
                    logger.warning("tracking.end_turn missing main invocation turn_id=%s; skipping write", tid)
                    return
                if not has_main_latency:
                    logger.warning("tracking.end_turn missing main latency turn_id=%s; skipping write", tid)
                    return
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
                final_context_tokens_est = int(
                    (out or {}).get(
                        "final_context_tokens_est",
                        prompt_system + prompt_history + prompt_rag + prompt_profile + prompt_other,
                    )
                    or 0
                )
                final_context_clipped = bool((out or {}).get("final_context_clipped", False))
                prompt_estimate_sum = int(prompt_system + prompt_history + prompt_rag + prompt_profile + prompt_other)
                if final_context_tokens_est != prompt_estimate_sum:
                    logger.warning(
                        "tracking.end_turn prompt sum mismatch turn_id=%s final_context=%s prompt_sum=%s; skipping write",
                        tid,
                        final_context_tokens_est,
                        prompt_estimate_sum,
                    )
                    return
                if (retrieved_count < 0) or (kept_count < 0) or (expanded_unique_chunks_after_merge < 0):
                    logger.warning("tracking.end_turn negative retrieval counters turn_id=%s; skipping write", tid)
                    return
                if kept_count > retrieved_count:
                    logger.warning("tracking.end_turn kept_count>retrieved_count turn_id=%s; skipping write", tid)
                    return
                rag_skip_reason = (out or {}).get("rag_skip_reason", (turn_rollup or {}).get("rag_skip_reason"))
                if rag_enabled:
                    rag_skip_reason = None
                else:
                    allowed_skip_reasons = {"disabled_by_route", "budget_zero", "retrieval_error", "no_candidates"}
                    if not isinstance(rag_skip_reason, str) or str(rag_skip_reason).strip() not in allowed_skip_reasons:
                        logger.warning("tracking.end_turn invalid/missing rag_skip_reason turn_id=%s; skipping write", tid)
                        return
                    rag_skip_reason = str(rag_skip_reason).strip()
                    if (retrieved_count != 0) or (kept_count != 0) or (expanded_unique_chunks_after_merge != 0) or (prompt_rag != 0):
                        logger.warning("tracking.end_turn rag_enabled=false counter invariant failed turn_id=%s; skipping write", tid)
                        return
                interactive_non_main_total = int((turn_rollup or {}).get("interactive_non_main_total_tokens_reported", 0))
                if int(mini_total) != int(interactive_non_main_total):
                    logger.warning("tracking.end_turn mini token rollup mismatch turn_id=%s; skipping write", tid)
                    return
                if int((turn_rollup or {}).get("main_invocation_count", 0)) != 1:
                    logger.warning("tracking.end_turn expected exactly one main invocation turn_id=%s; skipping write", tid)
                    return
                turn_started_mono = (turn_rollup or {}).get("_turn_started_monotonic", None)
                ttlt_turn_total = 0
                try:
                    if turn_started_mono is not None:
                        ttlt_turn_total = max(0, int((time.perf_counter() - float(turn_started_mono)) * 1000.0))
                except Exception:
                    ttlt_turn_total = 0
                if ttlt_turn_total < 0:
                    logger.warning("tracking.end_turn negative ttlt_ms_turn_total turn_id=%s; skipping write", tid)
                    return
                if main_streaming and ttfb_main is None:
                    logger.warning("tracking.end_turn missing streaming ttfb_ms_main turn_id=%s; skipping write", tid)
                    return
                if ttlt_main is None:
                    logger.warning("tracking.end_turn missing ttlt_ms_main turn_id=%s; skipping write", tid)
                    return

                provider_tokens_total = int((turn_rollup or {}).get("provider_tokens_total", 0))
                estimated_tokens_total = int((turn_rollup or {}).get("estimated_tokens_total", 0))
                zero_fallback_tokens_total = int((turn_rollup or {}).get("zero_fallback_tokens_total", 0))
                if estimated_tokens_total > 0:
                    turn_usage_source = "estimate"
                elif zero_fallback_tokens_total > 0:
                    turn_usage_source = "zero_fallback"
                else:
                    turn_usage_source = "provider"
                turn_usage_is_estimate = bool(turn_usage_source != "provider")

                invocations_count_total = int((turn_rollup or {}).get("invocations_count_total", 0))
                main_invocations_count = int((turn_rollup or {}).get("main_invocations_count", 0))
                mini_invocations_count = int((turn_rollup or {}).get("mini_invocations_count", 0))
                if invocations_count_total != (main_invocations_count + mini_invocations_count):
                    logger.warning("tracking.end_turn invocation count mismatch turn_id=%s; skipping write", tid)
                    return
                if main_invocations_count != 1:
                    logger.warning("tracking.end_turn main_invocations_count!=1 turn_id=%s; skipping write", tid)
                    return

                main_prompt_tokens_reported = self._as_int((turn_rollup or {}).get("main_prompt_tokens_reported"), None)
                main_completion_tokens_reported = self._as_int((turn_rollup or {}).get("main_completion_tokens_reported"), None)
                if (main_prompt_tokens_reported is not None) and (main_completion_tokens_reported is not None):
                    if int(main_total) != int(main_prompt_tokens_reported + main_completion_tokens_reported):
                        logger.warning("tracking.end_turn main token decomposition mismatch turn_id=%s; skipping write", tid)
                        return

                payload = {
                    "ts": _utc_iso(),
                    "event": "end_turn",
                    "run_id": self.run_id,
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
                    "final_context_tokens_est": int(final_context_tokens_est),
                    "final_context_clipped": bool(final_context_clipped),
                    "main_total_tokens_reported": main_total,
                    "mini_total_tokens_reported_sum": mini_total,
                    "turn_total_tokens_reported": int(main_total + mini_total),
                    "main_prompt_tokens_reported": main_prompt_tokens_reported,
                    "main_completion_tokens_reported": main_completion_tokens_reported,
                    "turn_usage_source": turn_usage_source,
                    "turn_usage_is_estimate": bool(turn_usage_is_estimate),
                    "provider_tokens_total": int(provider_tokens_total),
                    "estimated_tokens_total": int(estimated_tokens_total),
                    "zero_fallback_tokens_total": int(zero_fallback_tokens_total),
                    "ttfb_ms_main": (int(ttfb_main) if ttfb_main is not None else None),
                    "ttlt_ms_main": int(ttlt_main),
                    "ttlt_ms_turn_total": int(ttlt_turn_total),
                    "turn_start_ts": (turn_rollup or {}).get("_turn_start_ts"),
                    "invocations_count_total": int(invocations_count_total),
                    "main_invocations_count": int(main_invocations_count),
                    "mini_invocations_count": int(mini_invocations_count),
                }
                if not rag_enabled:
                    payload["rag_skip_reason"] = rag_skip_reason
                response_len = (out or {}).get("response_len")
                finish_reason = (out or {}).get("finish_reason")
                if response_len is not None:
                    payload["response_len"] = self._as_int(response_len, 0)
                if isinstance(finish_reason, str) and finish_reason.strip():
                    payload["finish_reason"] = finish_reason.strip()
                self._append_jsonl("turns.jsonl", payload)
                self._record_benchmark_turn_result(
                    turn_id=int(tid),
                    turn_payload=payload,
                    output_meta=(out if isinstance(out, dict) else {}),
                )
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
                schema_errors: list[Dict[str, Any]] = []
                purpose_value = str(purpose or "").strip()
                if not purpose_value:
                    schema_errors.append(
                        self._schema_error(
                            code="missing_required_key",
                            field="purpose",
                            expected="non-empty string",
                            actual=purpose,
                        )
                    )
                    purpose_value = "other"
                model_value = str(model or "").strip()
                meta_value: Dict[str, Any] = {}
                if meta is None:
                    meta_value = {}
                elif isinstance(meta, dict):
                    meta_value = dict(meta)
                else:
                    schema_errors.append(
                        self._schema_error(
                            code="type_mismatch",
                            field="meta",
                            expected="object",
                            actual=meta,
                        )
                    )
                self._invocation_state[invocation_id] = {
                    "turn_id": int(turn_id) if turn_id is not None else None,
                    "purpose": purpose_value,
                    "model": model_value,
                    "meta": meta_value,
                    "start_ts": start_ts,
                }
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
                state = self._invocation_state.get(invocation_id, {})
                schema_errors: list[Dict[str, Any]] = []
                if not state:
                    schema_errors.append(
                        self._schema_error(
                            code="invariant_violation",
                            field="invocation_id",
                            expected="known invocation_id from start_invocation",
                            actual=invocation_id,
                        )
                    )

                turn_id = state.get("turn_id")
                state_purpose = str(state.get("purpose") or "").strip()
                usage_purpose = str((usage or {}).get("purpose") or "").strip()
                if usage_purpose and state_purpose and usage_purpose != state_purpose:
                    schema_errors.append(
                        self._schema_error(
                            code="purpose_mismatch",
                            field="purpose",
                            expected=state_purpose,
                            actual=usage_purpose,
                        )
                    )
                if not state_purpose:
                    schema_errors.append(
                        self._schema_error(
                            code="missing_required_key",
                            field="purpose",
                            expected="non-empty string",
                            actual=state.get("purpose"),
                        )
                    )
                    state_purpose = "other"
                purpose = state_purpose

                state_model = str(state.get("model") or "").strip()
                usage_model = str((usage or {}).get("model") or "").strip()
                if not state_model and usage_model:
                    state_model = usage_model
                    if invocation_id in self._invocation_state:
                        self._invocation_state[invocation_id]["model"] = state_model
                elif state_model and usage_model and usage_model != state_model:
                    schema_errors.append(
                        self._schema_error(
                            code="model_mismatch",
                            field="model",
                            expected=state_model,
                            actual=usage_model,
                        )
                    )
                model = state_model
                if not model:
                    schema_errors.append(
                        self._schema_error(
                            code="missing_required_key",
                            field="model",
                            expected="non-empty string",
                            actual=state.get("model"),
                        )
                    )

                if purpose and model:
                    self._models_observed.setdefault(purpose, set()).add(model)
                streaming = bool((state.get("meta") or {}).get("streaming", False)) if isinstance(state.get("meta"), dict) else False
                prompt_tok = self._as_int((usage or {}).get("prompt_tokens_reported"), 0)
                completion_tok = self._as_int((usage or {}).get("completion_tokens_reported"), 0)
                total_tok = self._as_int((usage or {}).get("total_tokens_reported"), prompt_tok + completion_tok)
                usage_is_estimate_in = bool((usage or {}).get("usage_is_estimate", True))
                if total_tok <= 0:
                    total_tok = int(prompt_tok + completion_tok)

                usage_source_raw = str((usage or {}).get("usage_source") or "").strip()
                allowed_usage_sources = {"provider", "estimate", "zero_fallback"}
                if usage_source_raw and usage_source_raw not in allowed_usage_sources:
                    schema_errors.append(
                        self._schema_error(
                            code="enum_mismatch",
                            field="usage_source",
                            expected=["provider", "estimate", "zero_fallback"],
                            actual=usage_source_raw,
                        )
                    )
                    usage_source_raw = ""
                usage_source = usage_source_raw
                if not usage_source:
                    if usage_is_estimate_in:
                        usage_source = "estimate" if int(total_tok) > 0 else "zero_fallback"
                    else:
                        usage_source = "provider"
                usage_is_estimate = usage_source != "provider"
                if usage_is_estimate_in != usage_is_estimate:
                    schema_errors.append(
                        self._schema_error(
                            code="invariant_violation",
                            field="usage_is_estimate",
                            expected=usage_is_estimate,
                            actual=usage_is_estimate_in,
                            message="usage_is_estimate normalized to match usage_source",
                        )
                    )

                usage_estimate_method_raw = (usage or {}).get("usage_estimate_method")
                usage_estimate_method: Optional[str] = None
                if usage_estimate_method_raw is None:
                    usage_estimate_method = None
                elif isinstance(usage_estimate_method_raw, str):
                    usage_estimate_method = usage_estimate_method_raw.strip() or None
                else:
                    schema_errors.append(
                        self._schema_error(
                            code="type_mismatch",
                            field="usage_estimate_method",
                            expected="string|null",
                            actual=usage_estimate_method_raw,
                        )
                    )
                    usage_estimate_method = str(usage_estimate_method_raw)

                # Keep canonical fields stable and permit optional extra usage fields in meta diagnostics.
                meta_diag: Dict[str, Any] = {}
                if isinstance(state.get("meta"), dict):
                    meta_diag.update(state.get("meta", {}))
                else:
                    schema_errors.append(
                        self._schema_error(
                            code="type_mismatch",
                            field="meta",
                            expected="object",
                            actual=state.get("meta"),
                        )
                    )
                extra_usage = (usage or {}).get("extra_usage")
                if isinstance(extra_usage, dict):
                    meta_diag["extra_usage"] = extra_usage

                end_ts = _utc_iso()
                start_ts = state.get("start_ts")
                if not isinstance(start_ts, str) or not start_ts.strip():
                    schema_errors.append(
                        self._schema_error(
                            code="missing_required_key",
                            field="start_ts",
                            expected="utc-iso timestamp string",
                            actual=start_ts,
                        )
                    )
                    start_ts = end_ts
                ttlt_ms = self._to_non_negative_int_or_none((timing or {}).get("ttlt_ms"))
                if ttlt_ms is None:
                    start_ms = self._epoch_ms_from_iso(start_ts)
                    end_ms = self._epoch_ms_from_iso(end_ts)
                    if (start_ms is not None) and (end_ms is not None) and (end_ms >= start_ms):
                        ttlt_ms = int(end_ms - start_ms)
                    else:
                        logger.warning("tracking.ttlt_ms missing/invalid for invocation_id=%s; forcing 0", invocation_id)
                        ttlt_ms = 0
                first_token_ts = (timing or {}).get("first_token_ts")
                ttfb_ms: Optional[int]
                if streaming:
                    ttfb_ms = self._to_non_negative_int_or_none((timing or {}).get("ttfb_ms"))
                    if ttfb_ms is None:
                        logger.warning(
                            "tracking.streaming invocation missing/invalid ttfb_ms invocation_id=%s; setting null",
                            invocation_id,
                        )
                    if not isinstance(first_token_ts, str) or not first_token_ts.strip():
                        first_token_ts = None
                        ttfb_ms = None
                        logger.warning(
                            "tracking.streaming invocation had no first_token_ts invocation_id=%s; setting null",
                            invocation_id,
                        )
                    else:
                        first_token_ts = first_token_ts.strip()
                else:
                    # Non-streaming: first token and TTFB are not measured.
                    first_token_ts = None
                    ttfb_ms = None

                # 5.5.2 rollups: main contributes to main_total, non-main contributes to mini_total.
                if isinstance(turn_id, int):
                    ts = self._turn_state.setdefault(
                        int(turn_id),
                        self._turn_state_defaults(),
                    )
                    if purpose == "main":
                        ts["main_invocation_count"] = int(ts.get("main_invocation_count", 0)) + 1
                        ts["main_invocations_count"] = int(ts.get("main_invocations_count", 0)) + 1
                        ts["invocations_count_total"] = int(ts.get("invocations_count_total", 0)) + 1
                        ts["main_invocation_total_tokens_reported"] = int(
                            ts.get("main_invocation_total_tokens_reported", 0)
                        ) + int(total_tok)
                        ts["main_prompt_tokens_reported"] = int(prompt_tok)
                        ts["main_completion_tokens_reported"] = int(completion_tok)
                        ts["main_usage_is_estimate"] = bool(usage_is_estimate)
                        ts["main_streaming"] = bool(streaming)
                        ts["main_total_tokens_reported"] = int(ts.get("main_total_tokens_reported", 0)) + int(total_tok)
                        ts["ttfb_ms_main"] = (int(ttfb_ms) if ttfb_ms is not None else None)
                        ts["ttlt_ms_main"] = int(ttlt_ms)
                        ts["_has_main_latency"] = True
                    else:
                        ts["mini_total_tokens_reported_sum"] = int(ts.get("mini_total_tokens_reported_sum", 0)) + int(total_tok)
                        ts["mini_invocations_count"] = int(ts.get("mini_invocations_count", 0)) + 1
                        ts["invocations_count_total"] = int(ts.get("invocations_count_total", 0)) + 1
                        ts["interactive_non_main_total_tokens_reported"] = int(
                            ts.get("interactive_non_main_total_tokens_reported", 0)
                        ) + int(total_tok)
                    if usage_source == "provider":
                        ts["provider_tokens_total"] = int(ts.get("provider_tokens_total", 0)) + int(total_tok)
                    elif usage_source == "zero_fallback":
                        ts["zero_fallback_tokens_total"] = int(ts.get("zero_fallback_tokens_total", 0)) + int(total_tok)
                    else:
                        ts["estimated_tokens_total"] = int(ts.get("estimated_tokens_total", 0)) + int(total_tok)

                self._invocation_state.pop(invocation_id, None)
            except Exception as e:
                logger.warning("tracking.end_invocation failed: %s", e, exc_info=True)

    def record_stage(self, name: str, data: dict) -> None:
        with self._lock:
            try:
                if not self.run_id or self._ended:
                    return
                stage_name = str(name or "").strip()
                allowed_stages = {"retrieval_selection_expansion", "prompt_assembly"}
                if stage_name not in allowed_stages:
                    logger.warning("tracking.record_stage unknown stage name=%s; dropping record", stage_name)
                    return
                tid = _ACTIVE_TURN_ID.get()
                if not isinstance(tid, int):
                    logger.warning("tracking.record_stage missing active turn for stage=%s; dropping record", stage_name)
                    return
                if not isinstance(data, dict):
                    logger.warning("tracking.record_stage non-object data for stage=%s; coercing to empty", stage_name)
                    stage_data: Dict[str, Any] = {}
                else:
                    stage_data = dict(data)
                for forbidden in ("run_id", "turn_id", "ts", "event"):
                    if forbidden in stage_data:
                        logger.warning("tracking.record_stage removing forbidden key '%s' from stage data", forbidden)
                        stage_data.pop(forbidden, None)

                if stage_name == "prompt_assembly":
                    ts = self._turn_state.setdefault(
                        int(tid),
                        self._turn_state_defaults(),
                    )
                    ts["prompt_system_tokens_est"] = self._as_int(stage_data.get("prompt_system_tokens_est"), 0)
                    ts["prompt_history_tokens_est"] = self._as_int(stage_data.get("prompt_history_tokens_est"), 0)
                    ts["prompt_rag_tokens_est"] = self._as_int(stage_data.get("prompt_rag_tokens_est"), 0)
                    ts["prompt_profile_tokens_est"] = self._as_int(stage_data.get("prompt_profile_tokens_est"), 0)
                    ts["prompt_other_tokens_est"] = self._as_int(stage_data.get("prompt_other_tokens_est"), 0)
                if stage_name == "retrieval_selection_expansion":
                    ts = self._turn_state.setdefault(
                        int(tid),
                        self._turn_state_defaults(),
                    )
                    ts["route"] = str(stage_data.get("route") or ts.get("route") or "OTHER")
                    ts["rag_enabled"] = bool(stage_data.get("rag_enabled", True))
                    if not bool(ts.get("rag_enabled", False)):
                        ts["rag_skip_reason"] = stage_data.get("rag_skip_reason")
                    retrieved_count = self._as_int(
                        stage_data.get("retrieved_count", stage_data.get("ordered_count", stage_data.get("ordered_candidates"))),
                        0,
                    )
                    selected_count = self._as_int(
                        stage_data.get("selected_count", stage_data.get("selected_candidates", stage_data.get("kept_count"))),
                        0,
                    )
                    snippet_count_after_merge = self._as_int(
                        stage_data.get("snippet_count_after_merge", stage_data.get("kept_candidates")),
                        0,
                    )
                    expanded_unique_chunks_after_merge = self._as_int(
                        stage_data.get("expanded_unique_chunks_after_merge"),
                        snippet_count_after_merge,
                    )
                    ts["retrieved_count"] = int(retrieved_count or 0)
                    ts["kept_count"] = int(selected_count or 0)
                    ts["expanded_unique_chunks_after_merge"] = int(expanded_unique_chunks_after_merge or 0)

                    # Normalize emitted stage keys at instrumentation boundary while
                    # leaving RAG internals unchanged.
                    for deprecated in ("ordered_candidates", "selected_candidates", "kept_candidates", "ordered_count", "kept_count"):
                        stage_data.pop(deprecated, None)
                    stage_data["retrieved_count"] = int(retrieved_count or 0)
                    stage_data["selected_count"] = int(selected_count or 0)
                    stage_data["snippet_count_after_merge"] = int(snippet_count_after_merge or 0)
                    stage_data["expanded_unique_chunks_after_merge"] = int(expanded_unique_chunks_after_merge or 0)
                payload = {
                    "ts": _utc_iso(),
                    "event": "stage",
                    "run_id": self.run_id,
                    "name": stage_name,
                    "turn_id": int(tid),
                    "data": stage_data,
                }
                self._append_jsonl("turns.jsonl", payload)
            except Exception as e:
                logger.warning("tracking.record_stage failed: %s", e, exc_info=True)

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
        prompt_tol_abs = int(getattr(settings, "instrumentation_prompt_tol_abs_tokens", 25) or 25)
        prompt_tol_pct = float(getattr(settings, "instrumentation_prompt_tol_pct", 0.02) or 0.02)

        real = RealInstrumentation(
            runs_dir=runs_dir,
            mode=mode,
            run_id_override=run_id,
            prompt_tol_abs_tokens=prompt_tol_abs,
            prompt_tol_pct=prompt_tol_pct,
        )
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

