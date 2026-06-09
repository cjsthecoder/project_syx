"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Chat API endpoint for Syx AGI Chatbot Framework.

This module provides the main chat functionality via factory-backed LLM clients.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config import get_settings
from ..core.llm_service import generate_chat_response, get_llm_health
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..core.models import ChatRequest, ChatResponse
from ..llm_model.factory import get_llm_client
from ..tracking import get_instrumentation
from ..utils.errors import handle_llm_error, log_error_context
from ..utils.logging import (
    LLMLogger,
    RequestLogger,
    clear_message_id,
    clear_namespace,
    get_message_id,
    set_message_id,
)
from ..utils.tokens import count_tokens
from .chat_pipeline import ChatPipeline
from .chat_prompting import dump_prompt_debug, estimate_message_tokens, estimate_tokens

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()
_TURN_SEQ = 0
_TURN_SEQ_LOCK = threading.Lock()


def _next_turn_id() -> int:
    """Return the next monotonic turn id, incrementing a shared counter under a lock.

    Returns:
        The next strictly increasing turn id, unique per process across
        concurrent callers.
    """
    global _TURN_SEQ
    with _TURN_SEQ_LOCK:
        _TURN_SEQ += 1
        return int(_TURN_SEQ)


def _default_rag_metrics() -> Dict[str, Any]:
    """Return the baseline per-turn RAG metrics dict used before retrieval runs.

    Returns:
        A fresh metrics dict with neutral defaults (route ``OTHER``, RAG
        disabled, all counts zero). A new dict is returned each call so callers
        can mutate it safely.
    """
    return {
        "route": "OTHER",
        "rag_enabled": False,
        "retrieved_count": 0,
        "kept_count": 0,
        "expanded_unique_chunks_after_merge": 0,
        "rag_tokens_injected_est": 0,
        "final_context_clipped": False,
    }


@dataclass
class PreparedPrompts:
    """Bundle of prompt/context artifacts produced for a single chat turn.

    Attributes:
        conversation_history: Loaded working-memory messages, or ``None`` for an
            anonymous turn with no history.
        base_system_prompt: Resolved base system prompt for the turn.
        assistant_hint: Optional assistant priming hint.
        personality_creativity: Optional per-turn temperature override.
        rag_system_prompt: Retrieval-augmented context block, or ``None`` when
            RAG produced nothing.
        primary_ns: Primary namespace selected for the turn, if any.
        rag_metrics: Retrieval telemetry (route, candidate counts, scores)
            recorded for instrumentation.
    """

    conversation_history: Optional[list]
    base_system_prompt: Optional[str]
    assistant_hint: Optional[str]
    personality_creativity: Optional[float]
    rag_system_prompt: Optional[str]
    primary_ns: Optional[str]
    rag_metrics: Dict[str, Any]


def _prepare_prompts(
    pipeline: ChatPipeline,
    *,
    project_id: Optional[str],
    message: str,
    preview: str,
    msg_id: str,
) -> PreparedPrompts:
    """Build conversation history, prompts, and RAG context for a turn.

    Shared by the streaming and non-streaming endpoints so the prompt-assembly
    sequence stays identical. Does not enforce the model whitelist (callers do
    that explicitly so the failure surfaces at the call site).

    Args:
        pipeline: Pipeline used to build history, load prompts, and compute RAG.
        project_id: Active project id, or ``None`` for a project-less turn.
        message: Current user message.
        preview: Truncated message preview for debug logging.
        msg_id: Per-message correlation id.

    Returns:
        A ``PreparedPrompts`` with history, the RAG-augmented base system
        prompt, the assistant hint, personality creativity, the RAG context
        text, the primary namespace, and the turn RAG metrics.
    """
    conversation_history = pipeline.build_conversation_history(project_id)
    base_system_prompt, assistant_hint, personality_creativity = pipeline.load_project_prompts(
        project_id
    )
    rag_system_prompt, primary_ns, rag_metrics = pipeline.compute_rag_context(
        project_id=project_id,
        message=message,
        preview=preview,
        msg_id=msg_id,
        conversation_history=conversation_history,
    )
    base_system_prompt = pipeline.apply_rag_guidance(base_system_prompt, rag_system_prompt)
    return PreparedPrompts(
        conversation_history=conversation_history,
        base_system_prompt=base_system_prompt,
        assistant_hint=assistant_hint,
        personality_creativity=personality_creativity,
        rag_system_prompt=rag_system_prompt,
        primary_ns=primary_ns,
        rag_metrics=rag_metrics,
    )


def _turn_end_meta(
    rag_metrics: Optional[Dict[str, Any]],
    *,
    turn_id: int,
    project_id: Optional[str],
    conversation_id: Optional[str],
    streaming: bool,
    prompt_text: Optional[str],
    response_text: Optional[str],
    model_id: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the ``output_meta`` payload recorded at turn end.

    Centralizes the (otherwise duplicated) mapping of per-turn RAG metrics and
    turn identity into the instrumentation payload.

    Args:
        rag_metrics: Per-turn RAG metrics (route, counts, token estimates);
            ``None`` is treated as empty.
        turn_id: Monotonic turn id.
        project_id: Active project id.
        conversation_id: Conversation id from the request.
        streaming: Whether this turn used the streaming endpoint.
        prompt_text: User prompt text (coerced to ``str``).
        response_text: Assistant response text, or ``None`` if unavailable.
        model_id: Resolved model id for the turn.
        extra: Additional fields merged into the payload (e.g. ``response_len``
            or ``error``).

    Returns:
        The ``output_meta`` dict for ``Instrumentation.end_turn``.
    """
    m = rag_metrics or {}
    meta: Dict[str, Any] = {
        "turn_id": turn_id,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "streaming": streaming,
        "prompt_text": str(prompt_text or ""),
        "response_text": response_text,
        "model_id": model_id,
        "route": str(m.get("route", "OTHER")),
        "rag_enabled": bool(m.get("rag_enabled", False)),
        "retrieved_count": int(m.get("retrieved_count", 0) or 0),
        "kept_count": int(m.get("kept_count", 0) or 0),
        "expanded_unique_chunks_after_merge": int(
            m.get("expanded_unique_chunks_after_merge", 0) or 0
        ),
        "rag_tokens_injected_est": int(m.get("rag_tokens_injected_est", 0) or 0),
        "final_context_clipped": bool(m.get("final_context_clipped", False)),
    }
    if extra:
        meta.update(extra)
    return meta


def _update_context_token_stats(
    *,
    project_id: Optional[str],
    conversation_history: Optional[list],
    message: Optional[str],
    response_text: Optional[str],
    msg_id: str,
) -> None:
    """Estimate and persist the turn's context-token count (best-effort).

    Counts tokens across prior turns, the user message, and the assistant reply
    (the RAG system prompt is intentionally excluded), then records the total
    for the project. Failures are logged and swallowed; token stats are not a
    persistence invariant.

    Args:
        project_id: Project to record stats for; ``None`` skips persistence.
        conversation_history: Prior turns whose content is included.
        message: Current user message.
        response_text: Assistant reply text.
        msg_id: Per-message correlation id for logging.
    """
    try:
        combined_text = ""
        if conversation_history:
            for msg in conversation_history:
                combined_text += (msg.get("content") or "") + "\n"
        combined_text += message or ""
        combined_text += "\n" + (response_text or "")
        context_tokens = int(count_tokens(combined_text))
        if project_id:
            set_last_context_tokens(project_id, context_tokens)
    except Exception as exc:
        logger.warning(
            "chat.context_tokens update failed; operation=set_last_context_tokens project_id=%s message_id=%s detail=%s",
            project_id,
            msg_id,
            exc,
        )


def _build_stream_usage_payload(
    provider_usage: Optional[dict],
    msgs: list,
    full_text: str,
) -> Dict[str, Any]:
    """Resolve the usage payload to record for a streamed invocation.

    Prefers provider-reported usage when available; otherwise estimates token
    counts from the prompt messages and streamed text. When no provider usage
    is present and the estimate is non-positive, returns a zeroed estimate.

    Args:
        provider_usage: Usage reported by the provider during streaming, or
            ``None`` if the provider did not report usage.
        msgs: The prompt messages sent to the provider (for prompt-token
            estimation).
        full_text: The concatenated streamed completion text.

    Returns:
        A usage dict with reported/estimated prompt, completion, and total
        token counts plus an ``usage_is_estimate`` flag.
    """
    prompt_tokens_est = int(estimate_message_tokens(msgs))
    completion_tokens_est = int(estimate_tokens(full_text))
    total_tokens_est = int(prompt_tokens_est + completion_tokens_est)
    usage_payload = provider_usage or {
        "prompt_tokens_reported": int(prompt_tokens_est),
        "completion_tokens_reported": int(completion_tokens_est),
        "total_tokens_reported": int(total_tokens_est),
        "usage_is_estimate": True,
    }
    if not provider_usage and (
        not isinstance(usage_payload.get("total_tokens_reported"), int)
        or int(usage_payload.get("total_tokens_reported", 0)) <= 0
    ):
        usage_payload = {
            "prompt_tokens_reported": 0,
            "completion_tokens_reported": 0,
            "total_tokens_reported": 0,
            "usage_is_estimate": True,
        }
    return usage_payload


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint for user-AI conversation.

    Handles the core (non-streaming) chat flow using the shared LLM factory:
    builds conversation history and prompts, computes RAG context, enforces the
    model whitelist, generates the response, persists the user/assistant pair to
    project memory, updates context-token stats, and records turn-level
    instrumentation.

    Args:
        request: Chat request carrying the user message, optional project and
            conversation ids, and an optional model override.

    Returns:
        The assistant reply along with the conversation id, resolved model, and
        token usage.

    Raises:
        HTTPException: 500 on internal errors, or an LLM-specific error mapped
            by ``handle_llm_error`` when the failure originates from the LLM
            provider.
    """
    try:
        t0 = time.time()
        instr = get_instrumentation()
        turn_id = _next_turn_id()
        turn_started = False
        rag_turn_metrics: Dict[str, Any] = _default_rag_metrics()
        msg_id = str(uuid.uuid4())
        set_message_id(msg_id)
        proj = request.project_id or "Main"
        instr.start_turn(
            turn_id=turn_id,
            user_meta={
                "project_id": request.project_id,
                "conversation_id": request.conversation_id,
                "message_len": len(request.message or ""),
                "streaming": False,
            },
        )
        turn_started = True
        # (Telemetry removed)
        # Log the incoming request
        request_logger.log_request(endpoint="/chat", method="POST", user_id=request.conversation_id)
        # [PROMPT]
        settings = get_settings()
        preview = (request.message or "")[: settings.log_preview_max_chars]
        logger.debug(
            '[PROMPT] project_id=%s message_id=%s preview="%s"',
            proj,
            msg_id,
            preview,
        )

        pipeline = ChatPipeline(settings)
        memory_manager = get_memory_manager() if request.project_id else None
        prepared = _prepare_prompts(
            pipeline,
            project_id=request.project_id,
            message=request.message,
            preview=preview,
            msg_id=msg_id,
        )
        conversation_history = prepared.conversation_history
        base_system_prompt = prepared.base_system_prompt
        assistant_hint = prepared.assistant_hint
        personality_creativity = prepared.personality_creativity
        rag_system_prompt = prepared.rag_system_prompt
        primary_ns = prepared.primary_ns
        rag_turn_metrics = prepared.rag_metrics
        pipeline.enforce_model_whitelist(request.model)
        # Log LLM request
        try:
            logger.debug(
                '[PROMPT] base_sys_bytes=%s rag_sys_bytes=%s hint_bytes=%s base_sys_preview="%s"',
                len((base_system_prompt or "").encode("utf-8")),
                len((rag_system_prompt or "").encode("utf-8")),
                len((assistant_hint or "").encode("utf-8")),
                ((base_system_prompt or "")[:200].replace("\n", " ")),
            )
        except Exception as exc:  # pragma: no cover - defensive guard around debug logging only
            logger.debug("chat.prompt size logging failed message_id=%s detail=%s", msg_id, exc)
        llm_logger.log_llm_request(
            model=(request.model or settings.model_name),
            message_length=len(request.message),
            conversation_id=request.conversation_id,
        )

        logger.debug(
            f"Chat: model={request.model or 'default'} message_len={len(request.message)} conv_id={request.conversation_id}"
        )
        # Prompt debug snapshot (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            dump_prompt_debug(
                project_id=request.project_id,
                base_system_prompt=base_system_prompt,
                assistant_hint=assistant_hint,
                rag_system_prompt=rag_system_prompt,
                conversation_history=conversation_history,
                user_prompt=request.message,
                model=(request.model or settings.model_name),
            )
        except Exception as exc:
            logger.warning(
                "chat.prompt_debug dump failed; operation=write_debug_file project_id=%s message_id=%s detail=%s",
                request.project_id,
                msg_id,
                exc,
            )
        # Generate response using shared LLM runtime
        t_model0 = time.time()
        llm_response = generate_chat_response(
            message=request.message,
            conversation_history=conversation_history,
            base_system_prompt=base_system_prompt,
            assistant_hint=assistant_hint,
            rag_system_prompt=rag_system_prompt,
            override_model=request.model,
            temperature_override=personality_creativity,
        )
        t_model1 = time.time()

        # Check if LLM response was successful
        if not llm_response.get("success", False):
            raise Exception(llm_response.get("error", "Unknown LLM error"))

        # Log LLM response
        llm_logger.log_llm_response(
            model=llm_response.get("llm_model", settings.model_name),
            response_length=len(llm_response["response"]),
            tokens_used=llm_response.get("tokens_used"),
            conversation_id=request.conversation_id,
        )
        logger.debug(
            f"Chat: response_len={len(llm_response['response'])} tokens_used={llm_response.get('tokens_used')} model={llm_response.get('llm_model')}"
        )

        # Persist user and assistant messages (project-scoped working memory)
        try:
            if request.project_id and memory_manager is not None:
                is_chitchat = str(primary_ns or "").strip().lower() == "chitchat"
                prev_pair = pipeline.previous_pair_text(conversation_history)
                memory_manager.append_user_message(request.project_id, request.message)
                memory_manager.append_assistant_message(
                    request.project_id,
                    llm_response["response"],
                    namespace=(primary_ns or "other"),
                    user_text_for_tagging=request.message,
                    previous_pair_text_for_tagging=prev_pair,
                    forget=is_chitchat,
                    skip_tagger=is_chitchat,
                )
        except Exception as e:
            logger.error(
                "Persist failed project_id=%s message_id=%s detail=%s",
                request.project_id,
                msg_id,
                str(e),
                exc_info=True,
            )

        # Update context tokens for stats (exclude RAG system prompt)
        _update_context_token_stats(
            project_id=request.project_id,
            conversation_history=conversation_history,
            message=request.message,
            response_text=llm_response.get("response"),
            msg_id=msg_id,
        )

        # Create response
        response = ChatResponse(
            response=llm_response["response"],
            conversation_id=request.conversation_id,
            llm_model=llm_response.get("llm_model"),
            tokens_used=llm_response.get("tokens_used"),
        )

        # Log successful response
        latency_ms = int((time.time() - t0) * 1000)
        model_ms = int((t_model1 - t_model0) * 1000)
        resp_prev = (llm_response.get("response") or "")[: settings.log_preview_max_chars]
        logger.debug(
            '[RESPONSE] project_id=%s message_id=%s llm_model=%s tokens_used=%s latency_ms=%s model_ms=%s response_preview="%s"',
            proj,
            msg_id,
            llm_response.get("llm_model", ""),
            str(llm_response.get("tokens_used")),
            str(latency_ms),
            str(model_ms),
            resp_prev,
        )
        request_logger.log_response(
            endpoint="/chat",
            status_code=200,
            response_time=0.0,  # Would be calculated in real implementation
            user_id=request.conversation_id,
        )

        return response

    except Exception as e:
        # Log error
        request_logger.log_error(endpoint="/chat", error=e, user_id=request.conversation_id)
        # [ERROR]
        proj = request.project_id or "Main"
        mid = get_message_id() or "-"
        err_prev = (str(e) or "")[: get_settings().log_preview_max_chars]
        logger.debug(
            'project_id=%s message_id=%s error="%s"',
            proj,
            mid,
            err_prev,
        )

        # Log error context
        log_error_context(
            error=e,
            context={
                "endpoint": "/chat",
                "conversation_id": request.conversation_id,
                "project_id": request.project_id,
                "message_length": len(request.message),
            },
        )

        # Handle different types of errors
        if "llm" in str(e).lower() or "openai" in str(e).lower():
            raise handle_llm_error(e) from e
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": "Internal server error",
                    "error_code": "INTERNAL_ERROR",
                },
            ) from e
    finally:
        try:
            if "turn_started" in locals() and turn_started:
                _resp_text = None
                _model_id = request.model or settings.model_name
                if isinstance(locals().get("llm_response"), dict):
                    _resp_text = str(locals()["llm_response"].get("response") or "")
                    _model_id = str(locals()["llm_response"].get("llm_model") or _model_id)
                get_instrumentation().end_turn(
                    output_meta=_turn_end_meta(
                        rag_turn_metrics,
                        turn_id=turn_id,
                        project_id=request.project_id,
                        conversation_id=request.conversation_id,
                        streaming=False,
                        prompt_text=request.message,
                        response_text=_resp_text,
                        model_id=_model_id,
                    )
                )
        except Exception as exc:
            logger.warning(
                "chat.turn_end instrumentation failed; operation=end_turn project_id=%s turn_id=%s detail=%s",
                request.project_id,
                turn_id,
                exc,
            )
        clear_message_id()
        try:
            clear_namespace()
        except Exception as exc:  # pragma: no cover - defensive guard around context clear only
            logger.debug("chat.clear_namespace failed detail=%s", exc)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint that streams model tokens as they arrive.

    Builds prompts and RAG context like the non-streaming path, persists the
    user message immediately, then returns a streaming response that yields
    tokens incrementally and terminates with a ``::event: done`` marker. The
    assistant message is persisted and turn instrumentation finalized once the
    stream completes. Falls back to a simulated character-by-character stream
    when streaming is disabled in settings.

    Args:
        request: Chat request carrying the user message, optional project and
            conversation ids, and an optional model override.

    Returns:
        A ``StreamingResponse`` emitting plain-text token chunks on success, or
        a 500 ``JSONResponse`` describing the error.
    """
    settings = get_settings()
    instr = get_instrumentation()
    turn_id = _next_turn_id()
    turn_started = False
    turn_closed = False
    rag_turn_metrics: Dict[str, Any] = _default_rag_metrics()
    try:
        msg_id = str(uuid.uuid4())
        set_message_id(msg_id)
        instr.start_turn(
            turn_id=turn_id,
            user_meta={
                "project_id": request.project_id,
                "conversation_id": request.conversation_id,
                "message_len": len(request.message or ""),
                "streaming": True,
            },
        )
        turn_started = True
        request_logger.log_request(
            endpoint="/chat/stream", method="POST", user_id=request.conversation_id
        )

        pipeline = ChatPipeline(settings)
        prepared = _prepare_prompts(
            pipeline,
            project_id=request.project_id,
            message=(request.message or ""),
            preview=(request.message or "")[: settings.log_preview_max_chars],
            msg_id=msg_id,
        )
        conversation_history = prepared.conversation_history
        base_system_prompt = prepared.base_system_prompt
        assistant_hint = prepared.assistant_hint
        rag_system_prompt = prepared.rag_system_prompt
        primary_ns = prepared.primary_ns
        rag_turn_metrics = prepared.rag_metrics
        pipeline.enforce_model_whitelist(request.model)
        # Persist user immediately (streaming semantics)
        pipeline.persist_user(request.project_id, request.message)
        prev_pair = pipeline.previous_pair_text(conversation_history)
        is_chitchat = str(primary_ns or "").strip().lower() == "chitchat"
        # Fallback: if streaming is disabled, return a simulated stream using the non-streaming path
        if not settings.streaming_enabled:

            async def fake_stream():
                try:
                    resp = generate_chat_response(
                        message=request.message or "",
                        conversation_history=conversation_history,
                        base_system_prompt=base_system_prompt,
                        assistant_hint=assistant_hint,
                        rag_system_prompt=rag_system_prompt,
                    )
                    text = (resp or {}).get("response") or ""
                    # Persist assistant once complete
                    try:
                        if request.project_id:
                            pipeline.persist_assistant(
                                request.project_id,
                                text,
                                (primary_ns or "other"),
                                user_text_for_tagging=(request.message or ""),
                                previous_pair_text_for_tagging=prev_pair,
                                forget=is_chitchat,
                                skip_tagger=is_chitchat,
                            )
                    except Exception as exc:
                        logger.warning(
                            "chat.stream fake_stream assistant persist failed project_id=%s detail=%s",
                            request.project_id,
                            exc,
                        )
                    # Simulate streaming by yielding characters
                    for ch in text:
                        yield ch
                    yield "\n::event: done\n"
                except Exception as e:
                    yield f"\n[error] {str(e)}\n"

            return StreamingResponse(fake_stream(), media_type="text/plain; charset=utf-8")
        # True streaming via provider factory client
        msgs = pipeline.build_llm_messages(
            base_system_prompt=base_system_prompt,
            assistant_hint=assistant_hint,
            rag_system_prompt=rag_system_prompt,
            conversation_history=conversation_history,
            user_message=(request.message or ""),
        )
        # Prompt debug snapshot (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            dump_prompt_debug(
                project_id=request.project_id,
                base_system_prompt=base_system_prompt,
                assistant_hint=assistant_hint,
                rag_system_prompt=rag_system_prompt,
                conversation_history=conversation_history,
                user_prompt=(request.message or ""),
                model=(request.model or settings.model_name),
                msgs=msgs,
            )
        except Exception as exc:
            logger.warning(
                "chat.stream prompt_debug dump failed project_id=%s message_id=%s detail=%s",
                request.project_id,
                msg_id,
                exc,
            )

        # Token stream using factory-backed OpenAI streaming.
        async def token_stream():
            collected = []
            invocation_id = ""
            t_invoke0 = time.perf_counter()
            first_token_ms = None
            first_token_ts = None
            provider_usage: Optional[dict] = None
            try:
                model_name = request.model or settings.model_name
                invocation_id = instr.start_invocation(
                    purpose="main",
                    model=model_name,
                    meta={"streaming": True},
                )
                for piece, usage_obj in get_llm_client().stream_chat(
                    messages=msgs,
                    model=model_name,
                    temperature=1.0,
                    max_completion_tokens=int(settings.model_max_tokens),
                ):
                    if usage_obj is not None:
                        provider_usage = {
                            "prompt_tokens_reported": int(usage_obj.prompt_tokens_reported),
                            "completion_tokens_reported": int(usage_obj.completion_tokens_reported),
                            "total_tokens_reported": int(usage_obj.total_tokens_reported),
                            "usage_is_estimate": bool(usage_obj.usage_is_estimate),
                        }
                        if usage_obj.extra_usage:
                            provider_usage["extra_usage"] = usage_obj.extra_usage
                        continue
                    if isinstance(piece, str) and piece:
                        if first_token_ms is None:
                            first_token_ms = int((time.perf_counter() - t_invoke0) * 1000.0)
                            first_token_ts = datetime.now(timezone.utc).isoformat()
                        collected.append(piece)
                        yield piece
                # Signal end of stream
                yield "\n::event: done\n"
            finally:
                try:
                    full_text = "".join(collected)
                    usage_payload = _build_stream_usage_payload(provider_usage, msgs, full_text)
                    if invocation_id:
                        if first_token_ms is None:
                            logger.warning(
                                "chat.stream produced no first token timing; forcing ttfb_ms=0"
                            )
                        instr.end_invocation(
                            invocation_id,
                            usage={
                                "purpose": "main",
                                "model": (request.model or settings.model_name),
                                **usage_payload,
                            },
                            timing={
                                "ttfb_ms": int(first_token_ms or 0),
                                "ttlt_ms": int((time.perf_counter() - t_invoke0) * 1000.0),
                                "first_token_ts": first_token_ts,
                            },
                        )
                except Exception as exc:
                    logger.warning(
                        "chat.stream invocation instrumentation finalization failed project_id=%s detail=%s",
                        request.project_id,
                        exc,
                    )
                # Persist assistant once complete
                try:
                    if request.project_id:
                        full_text = "".join(collected)
                        pipeline.persist_assistant(
                            request.project_id,
                            full_text,
                            (primary_ns or "other"),
                            user_text_for_tagging=(request.message or ""),
                            previous_pair_text_for_tagging=prev_pair,
                            forget=is_chitchat,
                            skip_tagger=is_chitchat,
                        )
                except Exception as exc:
                    logger.warning(
                        "chat.stream assistant persist failed project_id=%s detail=%s",
                        request.project_id,
                        exc,
                    )
                try:
                    nonlocal turn_closed
                    if turn_started and not turn_closed:
                        final_text = "".join(collected)
                        instr.end_turn(
                            output_meta=_turn_end_meta(
                                rag_turn_metrics,
                                turn_id=turn_id,
                                project_id=request.project_id,
                                conversation_id=request.conversation_id,
                                streaming=True,
                                prompt_text=request.message,
                                response_text=final_text,
                                model_id=str(request.model or settings.model_name),
                                extra={"response_len": len(final_text)},
                            )
                        )
                        turn_closed = True
                except Exception as exc:
                    logger.warning(
                        "chat.stream turn_end failed; operation=end_turn project_id=%s turn_id=%s detail=%s",
                        request.project_id,
                        turn_id,
                        exc,
                    )

        return StreamingResponse(token_stream(), media_type="text/plain; charset=utf-8")
    except Exception as e:
        try:
            if turn_started and not turn_closed:
                instr.end_turn(
                    output_meta=_turn_end_meta(
                        rag_turn_metrics,
                        turn_id=turn_id,
                        project_id=request.project_id,
                        conversation_id=request.conversation_id,
                        streaming=True,
                        prompt_text=request.message,
                        response_text=None,
                        model_id=str(request.model or settings.model_name),
                        extra={"error": str(e)},
                    )
                )
                turn_closed = True
        except Exception as exc:
            logger.warning(
                "chat.stream error turn_end failed; operation=end_turn project_id=%s turn_id=%s detail=%s",
                request.project_id,
                turn_id,
                exc,
            )
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        clear_message_id()
        try:
            clear_namespace()
        except Exception as exc:  # pragma: no cover - defensive guard around context clear only
            logger.debug("chat.stream clear_namespace failed detail=%s", exc)


@router.get("/chat/health")
async def chat_health() -> JSONResponse:
    """Health check for chat functionality.

    Returns:
        A 200 ``JSONResponse`` reporting healthy status and the active model
        when the LLM is reachable; a 503 ``JSONResponse`` describing the
        failure otherwise.
    """
    try:
        # Check LLM health
        llm_health = get_llm_health()

        if llm_health["status"] == "healthy":
            return JSONResponse(
                status_code=200,
                content={
                    "status": "healthy",
                    "service": "chat",
                    "llm_status": llm_health["status"],
                    "model": llm_health.get("model", "unknown"),
                },
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "service": "chat",
                    "llm_status": llm_health["status"],
                    "error": llm_health.get("error", "Unknown error"),
                },
            )

    except Exception as e:
        logger.error(f"Chat health check failed: {str(e)}")
        return JSONResponse(
            status_code=503, content={"status": "unhealthy", "service": "chat", "error": str(e)}
        )


@router.get("/chat/stats")
async def chat_stats() -> JSONResponse:
    """Get chat statistics.

    Returns:
        A 200 ``JSONResponse`` with conversation/message counts, the active
        memory mode, and available features; a 500 ``JSONResponse`` on failure.
    """
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_stats()

        return JSONResponse(
            status_code=200,
            content={
                "conversations": stats["total_conversations"],
                "messages": stats["total_messages"],
                "memory_mode": stats["memory_mode"],
                "features": stats["features_available"],
            },
        )

    except Exception as e:
        logger.error(f"Failed to get chat stats: {str(e)}")
        return JSONResponse(
            status_code=500, content={"error": "Failed to retrieve statistics", "details": str(e)}
        )
