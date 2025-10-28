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


def _init_client() -> None:
    global _client, _enabled, _base_url
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
        logger.info("Langfuse telemetry enabled (session_id=%s)", _session_id)
    except Exception as e:  # pragma: no cover - defensive
        _client = None
        _enabled = False
        logger.warning("Langfuse init failed, telemetry disabled: %s", e)


def _client_ready() -> bool:
    return _enabled and _client is not None


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

        trace = _client.trace(
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
        span = trace.span(name=name, metadata=safe_meta)
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
        holder.event(name=name, metadata=safe_meta)
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


