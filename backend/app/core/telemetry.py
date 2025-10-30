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
_api_mode: str = "none"  # "v2" uses .trace/.span/.event, "v3" uses .start_as_current_span/.start_span/.create_event


class _V3Ctx:
    """Wrapper for Langfuse v3 current-span context manager.

    Holds the client and the active context manager to allow explicit end().
    """
    def __init__(self, client: Any, ctxmgr: Any) -> None:
        self._client = client
        self._cm = ctxmgr

    def start_span(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> "_V3Ctx":
        cm = self._client.start_as_current_span(name=name, metadata=metadata or {})
        cm.__enter__()
        return _V3Ctx(self._client, cm)

    def log_event(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        try:
            self._client.create_event(name=name, metadata=metadata or {})
        except Exception:
            pass

    def end(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        try:
            if metadata:
                # Attach metadata to the current span before closing
                self._client.update_current_span(metadata=metadata)
        except Exception:
            pass
        finally:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:
                pass


def _init_client() -> None:
    global _client, _enabled, _base_url, _api_mode
    settings = get_settings()
    _enabled = bool(settings.__dict__.get("langfuse_enabled", False))
    _base_url = settings.__dict__.get("langfuse_base_url")
    if not _enabled:
        logger.info("Langfuse init skipped: enabled=False")
        return
    try:
        # Lazy import to avoid hard dependency when disabled
        from langfuse import Langfuse  # type: ignore

        logger.info(
            "Langfuse init starting: enabled=%s host=%s pub_key=%s sec_key=%s",
            _enabled,
            _base_url,
            bool(settings.__dict__.get("langfuse_public_key")),
            bool(settings.__dict__.get("langfuse_secret_key")),
        )

        _client = Langfuse(
            public_key=settings.__dict__.get("langfuse_public_key"),
            secret_key=settings.__dict__.get("langfuse_secret_key"),
            host=_base_url,
            timeout=1.0,  # seconds
        )
        # Surface available methods for debugging
        try:
            attrs = dir(_client)
            interesting = [a for a in attrs if any(k in a for k in ("trace","span","event","start","log"))]
            logger.info("Langfuse client methods: %s", ",".join(sorted(interesting)[:30]))
        except Exception:
            pass
        # Detect API surface (SDKs differ between v2 and v3)
        if hasattr(_client, "trace"):
            _api_mode = "v2"
        elif hasattr(_client, "start_as_current_span") or hasattr(_client, "start_span"):
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
    logger.debug("start_trace called: client=%s enabled=%s mode=%s", bool(_client), _enabled, _api_mode)
    if _client is None and get_settings():
        # Initialize on first use
        _init_client()
        logger.debug("post-init: client=%s enabled=%s mode=%s", bool(_client), _enabled, _api_mode)

    if not _client_ready():
        return _NoopTrace()

    try:
        user_id = "local_user"
        meta = metadata or {}
        # Ensure truncation for any text fields in metadata
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}

        if _api_mode == "v2" and hasattr(_client, "trace"):
            trace = _client.trace(
                name=name,
                user_id=user_id,
                session_id=_session_id,
                metadata=safe_meta,
            )
        elif _api_mode == "v3" and (hasattr(_client, "start_as_current_span") or hasattr(_client, "start_span")):
            # v3: use current-span context manager
            if hasattr(_client, "start_as_current_span"):
                cm = _client.start_as_current_span(name=name, metadata=safe_meta)
            else:
                cm = _client.start_span(name=name, metadata=safe_meta)
            cm.__enter__()
            trace = _V3Ctx(_client, cm)
        else:
            logger.warning("Langfuse: no compatible trace creation method found (mode=%s)", _api_mode)
            return _NoopTrace()
        # Best-effort log a view link if available
        try:
            url = None
            if hasattr(trace, "url"):
                url = getattr(trace, "url", None)
            elif hasattr(_client, "get_trace_url"):
                # best-effort when supported
                url = _client.get_trace_url()
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
        elif _api_mode == "v3" and (hasattr(_client, "start_as_current_span") or hasattr(_client, "start_span")):
            if hasattr(_client, "start_as_current_span"):
                cm = _client.start_as_current_span(name=name, metadata=safe_meta)
            else:
                cm = _client.start_span(name=name, metadata=safe_meta)
            cm.__enter__()
            span = _V3Ctx(_client, cm)
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
        elif _api_mode == "v3" and hasattr(_client, "create_event"):
            _client.create_event(name=name, metadata=safe_meta)
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse log_event failed: %s", e)
        return None


def end_span(span: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not _client_ready():
        return None
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        if _api_mode == "v2" and hasattr(span, "end"):
            span.end(metadata=safe_meta)
        elif _api_mode == "v3":
            try:
                if metadata and hasattr(_client, "update_current_span"):
                    _client.update_current_span(metadata=safe_meta)
            finally:
                try:
                    if isinstance(span, _V3Ctx):
                        span.end({})
                except Exception:
                    pass
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse end_span failed: %s", e)
        return None


def end_trace(trace: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    if not _client_ready():
        return None
    try:
        meta = metadata or {}
        safe_meta = {k: (_truncate(v) if isinstance(v, str) else v) for k, v in meta.items()}
        if _api_mode == "v2" and hasattr(trace, "end"):
            trace.end(metadata=safe_meta)
        elif _api_mode == "v3":
            try:
                if metadata and hasattr(_client, "update_current_trace"):
                    _client.update_current_trace(metadata=safe_meta)
            finally:
                try:
                    if isinstance(trace, _V3Ctx):
                        trace.end({})
                except Exception:
                    pass
    except Exception as e:  # pragma: no cover
        logger.warning("Langfuse end_trace failed: %s", e)
        return None


