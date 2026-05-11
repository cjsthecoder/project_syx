"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Chat API endpoint for Syx AGI Chatbot Framework.

This module provides the main chat functionality via factory-backed LLM clients.
"""

import logging
import time
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.models import ChatRequest, ChatResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..llm_model.factory import get_llm_client
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..utils.logging import RequestLogger, LLMLogger, set_message_id, clear_message_id, get_message_id, clear_namespace
from ..utils.errors import handle_llm_error, log_error_context
from ..core.config import get_settings
from ..tracking import get_instrumentation
from ..utils.tokens import count_tokens
from .chat_prompting import dump_prompt_debug, estimate_message_tokens, estimate_tokens
from .chat_pipeline import ChatPipeline

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()
_TURN_SEQ = 0
_TURN_SEQ_LOCK = threading.Lock()

def _next_turn_id() -> int:
    global _TURN_SEQ
    with _TURN_SEQ_LOCK:
        _TURN_SEQ += 1
        return int(_TURN_SEQ)

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint handles the core chat functionality using the shared LLM factory.
    It supports conversation history and project context (stubbed).
    """
    try:
        t0 = time.time()
        instr = get_instrumentation()
        turn_id = _next_turn_id()
        turn_started = False
        rag_turn_metrics: Dict[str, Any] = {
            "route": "OTHER",
            "rag_enabled": False,
            "retrieved_count": 0,
            "kept_count": 0,
            "expanded_unique_chunks_after_merge": 0,
            "rag_tokens_injected_est": 0,
            "final_context_clipped": False,
        }
        msg_id = str(uuid.uuid4())
        set_message_id(msg_id)
        proj = request.project_id or "Continuum"
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
        preview = (request.message or "")[:settings.log_preview_max_chars]
        logger.debug(
            "[PROMPT] project_id=%s message_id=%s preview=\"%s\"",
            proj,
            msg_id,
            preview,
        )

        pipeline = ChatPipeline(settings)
        memory_manager = get_memory_manager() if request.project_id else None
        conversation_history = pipeline.build_conversation_history(request.project_id)
        base_system_prompt, assistant_hint, personality_creativity = pipeline.load_project_prompts(request.project_id)
        rag_system_prompt, primary_ns, rag_turn_metrics = pipeline.compute_rag_context(
            project_id=request.project_id,
            message=request.message,
            preview=preview,
            msg_id=msg_id,
            conversation_history=conversation_history,
        )
        base_system_prompt = pipeline.apply_rag_guidance(base_system_prompt, rag_system_prompt)
        pipeline.enforce_model_whitelist(request.model)
        # Log LLM request
        try:
            logger.debug(
                "[PROMPT] base_sys_bytes=%s rag_sys_bytes=%s hint_bytes=%s base_sys_preview=\"%s\"",
                len((base_system_prompt or "").encode("utf-8")),
                len((rag_system_prompt or "").encode("utf-8")),
                len((assistant_hint or "").encode("utf-8")),
                ((base_system_prompt or "")[:200].replace("\n", " ")),
            )
        except Exception as exc:
            logger.debug("chat.prompt size logging failed message_id=%s detail=%s", msg_id, exc)
        llm_logger.log_llm_request(
            model=(request.model or settings.model_name),
            message_length=len(request.message),
            conversation_id=request.conversation_id
        )
        
        logger.debug(f"Chat: model={request.model or 'default'} message_len={len(request.message)} conv_id={request.conversation_id}")
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
            conversation_id=request.conversation_id
        )
        logger.debug(f"Chat: response_len={len(llm_response['response'])} tokens_used={llm_response.get('tokens_used')} model={llm_response.get('llm_model')}")
        
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
        try:
            combined_text = ''
            if conversation_history:
                for msg in conversation_history:
                    combined_text += (msg.get('content') or '') + '\n'
            combined_text += request.message or ''
            # Include the assistant's latest reply
            combined_text += '\n' + (llm_response.get('response') or '')
            context_tokens = int(count_tokens(combined_text))
            if request.project_id:
                set_last_context_tokens(request.project_id, context_tokens)
        except Exception as exc:
            logger.warning(
                "chat.context_tokens update failed; operation=set_last_context_tokens project_id=%s message_id=%s detail=%s",
                request.project_id,
                msg_id,
                exc,
            )
        
        # Create response
        response = ChatResponse(
            response=llm_response["response"],
            conversation_id=request.conversation_id,
            llm_model=llm_response.get("llm_model"),
            tokens_used=llm_response.get("tokens_used")
        )
        
        # Log successful response
        latency_ms = int((time.time() - t0) * 1000)
        model_ms = int((t_model1 - t_model0) * 1000)
        resp_prev = (llm_response.get("response") or "")[:settings.log_preview_max_chars]
        logger.debug(
            "[RESPONSE] project_id=%s message_id=%s llm_model=%s tokens_used=%s latency_ms=%s model_ms=%s response_preview=\"%s\"",
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
            user_id=request.conversation_id
        )
        
        return response
        
    except Exception as e:
        # Log error
        request_logger.log_error(endpoint="/chat", error=e, user_id=request.conversation_id)
        # [ERROR]
        proj = request.project_id or "Continuum"
        mid = get_message_id() or "-"
        err_prev = (str(e) or "")[:get_settings().log_preview_max_chars]
        logger.debug(
            "project_id=%s message_id=%s error=\"%s\"",
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
                "message_length": len(request.message)
            }
        )
        
        # Handle different types of errors
        if "llm" in str(e).lower() or "openai" in str(e).lower():
            raise handle_llm_error(e)
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": "Internal server error",
                    "error_code": "INTERNAL_ERROR"
                }
            )
    finally:
        try:
            if "turn_started" in locals() and turn_started:
                _resp_text = None
                _model_id = (request.model or settings.model_name)
                if isinstance(locals().get("llm_response"), dict):
                    _resp_text = str(locals()["llm_response"].get("response") or "")
                    _model_id = str(locals()["llm_response"].get("llm_model") or _model_id)
                get_instrumentation().end_turn(
                    output_meta={
                        "turn_id": turn_id,
                        "project_id": request.project_id,
                        "conversation_id": request.conversation_id,
                        "streaming": False,
                        "route": str((rag_turn_metrics or {}).get("route", "OTHER")),
                        "rag_enabled": bool((rag_turn_metrics or {}).get("rag_enabled", False)),
                        "retrieved_count": int((rag_turn_metrics or {}).get("retrieved_count", 0) or 0),
                        "kept_count": int((rag_turn_metrics or {}).get("kept_count", 0) or 0),
                        "expanded_unique_chunks_after_merge": int(
                            (rag_turn_metrics or {}).get("expanded_unique_chunks_after_merge", 0) or 0
                        ),
                        "rag_tokens_injected_est": int(
                            (rag_turn_metrics or {}).get("rag_tokens_injected_est", 0) or 0
                        ),
                        "final_context_clipped": bool((rag_turn_metrics or {}).get("final_context_clipped", False)),
                        "prompt_text": str(request.message or ""),
                        "response_text": _resp_text,
                        "model_id": _model_id,
                    }
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
        except Exception as exc:
            logger.debug("chat.clear_namespace failed detail=%s", exc)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint.
    Streams model tokens to the client as they arrive.
    """
    settings = get_settings()
    instr = get_instrumentation()
    turn_id = _next_turn_id()
    turn_started = False
    turn_closed = False
    rag_turn_metrics: Dict[str, Any] = {
        "route": "OTHER",
        "rag_enabled": False,
        "retrieved_count": 0,
        "kept_count": 0,
        "expanded_unique_chunks_after_merge": 0,
        "rag_tokens_injected_est": 0,
        "final_context_clipped": False,
    }
    try:
        t0 = time.time()
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
        request_logger.log_request(endpoint="/chat/stream", method="POST", user_id=request.conversation_id)
        proj = request.project_id or "Continuum"

        pipeline = ChatPipeline(settings)
        conversation_history = pipeline.build_conversation_history(request.project_id)
        base_system_prompt, assistant_hint, personality_creativity = pipeline.load_project_prompts(request.project_id)
        rag_system_prompt, primary_ns, rag_turn_metrics = pipeline.compute_rag_context(
            project_id=request.project_id,
            message=(request.message or ""),
            preview=(request.message or "")[:settings.log_preview_max_chars],
            msg_id=msg_id,
            conversation_history=conversation_history,
        )
        base_system_prompt = pipeline.apply_rag_guidance(base_system_prompt, rag_system_prompt)
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
                model_name = (request.model or settings.model_name)
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
                    prompt_tokens_est = int(estimate_message_tokens(msgs))
                    completion_tokens_est = int(estimate_tokens(full_text))
                    total_tokens_est = int(prompt_tokens_est + completion_tokens_est)
                    usage_payload = provider_usage or {
                        "prompt_tokens_reported": int(prompt_tokens_est),
                        "completion_tokens_reported": int(completion_tokens_est),
                        "total_tokens_reported": int(total_tokens_est),
                        "usage_is_estimate": True,
                    }
                    if (
                        not provider_usage
                        and (
                            not isinstance(usage_payload.get("total_tokens_reported"), int)
                            or int(usage_payload.get("total_tokens_reported", 0)) <= 0
                        )
                    ):
                        usage_payload = {
                            "prompt_tokens_reported": 0,
                            "completion_tokens_reported": 0,
                            "total_tokens_reported": 0,
                            "usage_is_estimate": True,
                        }
                    if invocation_id:
                        if first_token_ms is None:
                            logger.warning("chat.stream produced no first token timing; forcing ttfb_ms=0")
                        instr.end_invocation(
                            invocation_id,
                            usage={"purpose": "main", "model": (request.model or settings.model_name), **usage_payload},
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
                        instr.end_turn(
                            output_meta={
                                "turn_id": turn_id,
                                "project_id": request.project_id,
                                "conversation_id": request.conversation_id,
                                "streaming": True,
                                "response_len": len("".join(collected)),
                                "prompt_text": str(request.message or ""),
                                "response_text": "".join(collected),
                                "model_id": str(request.model or settings.model_name),
                                "route": str((rag_turn_metrics or {}).get("route", "OTHER")),
                                "rag_enabled": bool((rag_turn_metrics or {}).get("rag_enabled", False)),
                                "retrieved_count": int((rag_turn_metrics or {}).get("retrieved_count", 0) or 0),
                                "kept_count": int((rag_turn_metrics or {}).get("kept_count", 0) or 0),
                                "expanded_unique_chunks_after_merge": int(
                                    (rag_turn_metrics or {}).get("expanded_unique_chunks_after_merge", 0) or 0
                                ),
                                "rag_tokens_injected_est": int(
                                    (rag_turn_metrics or {}).get("rag_tokens_injected_est", 0) or 0
                                ),
                                "final_context_clipped": bool(
                                    (rag_turn_metrics or {}).get("final_context_clipped", False)
                                ),
                            }
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
                    output_meta={
                        "turn_id": turn_id,
                        "project_id": request.project_id,
                        "conversation_id": request.conversation_id,
                        "streaming": True,
                        "error": str(e),
                        "prompt_text": str(request.message or ""),
                        "response_text": None,
                        "model_id": str(request.model or settings.model_name),
                        "route": str((rag_turn_metrics or {}).get("route", "OTHER")),
                        "rag_enabled": bool((rag_turn_metrics or {}).get("rag_enabled", False)),
                        "retrieved_count": int((rag_turn_metrics or {}).get("retrieved_count", 0) or 0),
                        "kept_count": int((rag_turn_metrics or {}).get("kept_count", 0) or 0),
                        "expanded_unique_chunks_after_merge": int(
                            (rag_turn_metrics or {}).get("expanded_unique_chunks_after_merge", 0) or 0
                        ),
                        "rag_tokens_injected_est": int(
                            (rag_turn_metrics or {}).get("rag_tokens_injected_est", 0) or 0
                        ),
                        "final_context_clipped": bool(
                            (rag_turn_metrics or {}).get("final_context_clipped", False)
                        ),
                    }
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
        except Exception as exc:
            logger.debug("chat.stream clear_namespace failed detail=%s", exc)

@router.get("/chat/health")
async def chat_health() -> JSONResponse:
    """Health check for chat functionality."""
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
                    "model": llm_health.get("model", "unknown")
                }
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "service": "chat",
                    "llm_status": llm_health["status"],
                    "error": llm_health.get("error", "Unknown error")
                }
            )
            
    except Exception as e:
        logger.error(f"Chat health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "chat",
                "error": str(e)
            }
        )


@router.get("/chat/stats")
async def chat_stats() -> JSONResponse:
    """Get chat statistics."""
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_stats()
        
        return JSONResponse(
            status_code=200,
            content={
                "conversations": stats["total_conversations"],
                "messages": stats["total_messages"],
                "memory_mode": stats["memory_mode"],
                "features": stats["features_available"]
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get chat stats: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to retrieve statistics",
                "details": str(e)
            }
        )
