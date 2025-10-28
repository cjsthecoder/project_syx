"""
Langfuse telemetry integration (V2.4.2).

Fail-open, lightweight helpers for traces, spans, and events.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any, Dict, Optional

from .config import get_settings

logger = logging.getLogger(__name__)


def _truncate(text: Optional[str], max_len: int = 200) -> Optional[str]:
    if not isinstance(text, str):
        return text
    if len(text) <= max_len:
        return text
    return text[:max_len]


class _NoopTrace:
    def __init__(self) -> None:
        self.id = str(uuid.uuid4())

    def start_span(self, name: str, **kwargs) -> "_NoopSpan":
        return _NoopSpan()

    def log_event(self, name: str, **kwargs) -> None:
        return None

    def end(self, **kwargs) -> None:
        return None

    @property
    def url(self) -> Optional[str]:
        return None


class _NoopSpan:
    def __init__(self) -> None:
        self.id = str(uuid.uuid4())

    def log_event(self, name: str, **kwargs) -> None:
        return None

    def end(self, **kwargs) -> None:
        return None


_client = None
_enabled = False
_base_url: Optional[str] = None
_session_id: str = str(uuid.uuid4())
_api_mode: str = "none"  # "v2" uses .trace/.span/.event, "v3" uses .start_trace/.start_span/.log_event


def _init_client() -> None:
    global _client, _enabled, _base_url, _api_mode
    settings = get_settings()
    _enabled = bool(settings.__dict__.get("langfuse_enabled", False))
    _base_url = settings.__dict__.get("langfuse_base_url")
    if not _enabled:
        return
    try:
        # Lazy import to avoid hard dependency when disabled
        from langfuse import Langfuse  # type: ignore

        _client = Langfuse(
            public_key=settings.__dict__.get("langfuse_public_key"),
            secret_key=settings.__dict__.get("langfuse_secret_key"),
            host=_base_url,
            timeout=1.0,  # seconds
        )
        # Detect API surface (SDKs differ between v2 and v3)
        if hasattr(_client, "trace"):
            _api_mode = "v2"
        elif hasattr(_client, "start_trace"):
            _api_mode = "v3"
        else:
            _api_mode = "none"
            _enabled = False
            logger.warning("Langfuse client lacks trace APIs, telemetry will no-op. Consider installing langfuse>=2.x or 3.x.")
        if _enabled and _api_mode in ("v2", "v3"):
            logger.info("Langfuse telemetry enabled (mode=%s, session_id=%s)", _api_mode, _session_id)
    except Exception as e:  # pragma: no cover - defensive
        _client = None
        _enabled = False
        logger.warning("Langfuse init failed, telemetry disabled: %s", e)


def _client_ready() -> bool:
    return _enabled and _client is not None and _api_mode in ("v2", "v3")


def start_trace(name: str, metadata: Optional[Dict[str, Any]] = None) -> Any:
    """Start a trace. Returns a trace object with .start_span(), .log_event(), .end().
    Fail-open to a noop trace on any error.
    """
    if _client is None and get_settings():
        # Initialize on first use
        _init_client()

    if not _client_ready():
        return _NoopTrace()

    try:
        user_id = "local_user"
        meta = metadata or {}
        # Ensure truncation for any text fields in metadata
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}

        if _api_mode == "v2":
            trace = _client.trace(
                name=name,
                user_id=user_id,
                session_id=_session_id,
                metadata=safe_meta,
            )
        else:  # v3
            # v3 exposes start_trace and returns a trace object
            trace = _client.start_trace(
                name=name,
                user_id=user_id,
                session_id=_session_id,
                metadata=safe_meta,
            )
        # Best-effort log a view link if available
        try:
            url = getattr(trace, "url", None)
            if url:
                logger.info("Langfuse trace started: %s", url)
        except Exception:
            pass
        return trace
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Langfuse start_trace failed: %s", e)
        return _NoopTrace()


def start_span(trace: Any, name: str, metadata: Optional[Dict[str, Any]] = None) -> Any:
    if not _client_ready():
        return _NoopSpan()
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        if hasattr(trace, "span") and _api_mode == "v2":
            span = trace.span(name=name, metadata=safe_meta)
        elif hasattr(trace, "start_span"):
            span = trace.start_span(name=name, metadata=safe_meta)
        else:
            return _NoopSpan()
        return span
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse start_span failed: %s", e)
        return _NoopSpan()


def log_event(holder: Any, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not _client_ready():
        return None
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        if hasattr(holder, "event") and _api_mode == "v2":
            holder.event(name=name, metadata=safe_meta)
        elif hasattr(holder, "log_event"):
            holder.log_event(name=name, metadata=safe_meta)
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse log_event failed: %s", e)
        return None


def end_span(span: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not _client_ready():
        return None
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        span.end(metadata=safe_meta)
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse end_span failed: %s", e)
        return None


def end_trace(trace: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not _client_ready():
        return None
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        trace.end(metadata=safe_meta)
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse end_trace failed: %s", e)
        return None


