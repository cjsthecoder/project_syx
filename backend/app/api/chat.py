"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Chat API endpoint for Morpheus AGI Chatbot Framework.

This module provides the main chat functionality with LangChain integration.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.models import ChatRequest, ChatResponse, ErrorResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..utils.debug_utils import write_debug_file
from ..utils.logging import RequestLogger, LLMLogger, set_message_id, clear_message_id, get_message_id, set_route, clear_route, set_namespace, clear_namespace, get_route
from ..core.rag_manager import _load_route_config
from ..utils.errors import handle_llm_error, log_error_context
from ..core.config import get_settings, get_model_config
from ..core.rag_manager import retrieve_context, merge_daily_and_main
from ..core.personality import load_project_system_prompt, load_project_personality
from ..core.daily_rag import start_daily_cache_rebuild
from ..core.database import get_session
from ..core.db_models import Project
from ..core.query_builder import build_query
from itertools import islice
from langchain_openai import ChatOpenAI
try:
    # Preferred path for LC 0.2.x
    from langchain.callbacks.streaming_aiter import AsyncIteratorCallbackHandler  # type: ignore
except Exception:
    try:
        from langchain.callbacks import AsyncIteratorCallbackHandler  # type: ignore
    except Exception:
        AsyncIteratorCallbackHandler = None  # type: ignore
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()

RAG_SYSTEM_PROMPT = """Each retrieved snippet includes a similarity score in the range [0.0–1.0].
The similarity score reflects semantic closeness to the query, not factual correctness.

Guidance for use:
- Higher scores indicate stronger semantic relevance to the current query.
- Prefer high-scoring snippets when making factual claims or direct assertions.
- Lower-scoring snippets may be used for background, framing, or creative inspiration.
- Do not treat lower-scoring snippets as authoritative unless supported by higher-scoring context.

When multiple snippets conflict:
- Favor information from higher-scoring snippets.
- If only lower-scoring snippets are available, respond cautiously and note uncertainty.
"""

def _estimate_tokens(text: str) -> int:
    """Best-effort token estimate for debug headers."""
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return int(len(enc.encode(text or "")))
    except Exception:
        return int(len((text or "").split()))

def _dump_prompt_debug(
    *,
    project_id: Optional[str],
    base_system_prompt: Optional[str],
    assistant_hint: Optional[str],
    rag_system_prompt: Optional[str],
    conversation_history: Optional[list[dict]],
    user_prompt: Optional[str],
    model: Optional[str],
) -> None:
    """
    Write a prompt debug snapshot to memory/{project_id}/debug/prompts/.
    Safe/no-op when project_id is missing or debug files are disabled.
    """
    if not project_id:
        return
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    fname = f"{ts}_{project_id}_query.txt"
    route = None
    try:
        route = get_route()
    except Exception:
        route = None
    rag_used = bool(rag_system_prompt)

    # Build conversation history section
    hist_lines: list[str] = []
    if conversation_history:
        for m in conversation_history:
            role = (m.get("role") or "").lower()
            content = (m.get("content") or "")
            if role == "user":
                hist_lines.append("USER:")
                hist_lines.append(content)
                hist_lines.append("")
            elif role == "assistant":
                hist_lines.append("ASSISTANT:")
                hist_lines.append(content)
                hist_lines.append("")
            else:
                hist_lines.append(f"{role.upper()}:")
                hist_lines.append(content)
                hist_lines.append("")
    hist_text = "\n".join(hist_lines).rstrip() + ("\n" if hist_lines else "")

    body = (
        f"# timestamp: {ts}\n"
        + (f"# project_id: {project_id}\n" if project_id else "")
        + (f"# route: {route}\n" if route else "")
        + f"# rag: {str(bool(rag_used)).lower()}\n"
        + (f"# model: {model}\n" if model else "")
    )
    # Estimate tokens over the whole formatted dump (best-effort)
    payload_preview = (
        "=== SYSTEM ===\n"
        + (base_system_prompt or "")
        + "\n\n=== ASSISTANT_HINT ===\n"
        + (assistant_hint or "")
        + "\n\n=== SYSTEM (RAG CONTEXT) ===\n"
        + (rag_system_prompt or "")
        + "\n\n=== CONVERSATION HISTORY ===\n"
        + hist_text
        + "\n=== USER PROMPT ===\n"
        + (user_prompt or "")
        + "\n"
    )
    body += f"# total_tokens_estimate: {_estimate_tokens(body + payload_preview)}\n\n"
    body += payload_preview

    write_debug_file(project_id, f"prompts/{fname}", body)


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint handles the core chat functionality using LangChain ChatOpenAI.
    It supports conversation history and project context (stubbed for V4).
    """
    try:
        t0 = time.time()
        msg_id = str(uuid.uuid4())
        set_message_id(msg_id)
        proj = request.project_id or "Continuum"
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

        # Build conversation history from per-project working memory (V2.2)
        conversation_history = None
        if request.project_id:
            memory_manager = get_memory_manager()
            proj_msgs = memory_manager.get_project_history(request.project_id)
            # chronological messages already; map to role/content for LLM
            conversation_history = [{"role": m["role"], "content": m["content"]} for m in proj_msgs]

        # V2.6: Load project system prompt and personality (if project context)
        base_system_prompt = None
        assistant_hint = None
        personality_creativity = None
        if request.project_id:
            try:
                base_system_prompt = load_project_system_prompt(request.project_id)
                p = load_project_personality(request.project_id)
                personality_creativity = float(p.get("creativity") or 0.0)
                # Assistant hint using standard template
                tone = p.get("tone") or "analytical"
                verb = p.get("verbosity") or "concise"
                fmt = p.get("format") or "markdown"
                domains = p.get("domain_focus") or []
                if not isinstance(domains, list):
                    domains = []
                assistant_hint = (
                    f"Follow these preferences: tone={tone}, verbosity={verb}, format={fmt}, "
                    f"domain_focus={domains}. Respond concisely in the chosen format."
                )
            except Exception:
                base_system_prompt = None
                assistant_hint = None
                personality_creativity = None

        # Optional RAG retrieval (V2.3.1: builder + daily/main merge)
        rag_system_prompt = None
        primary_ns = None
        if settings.rag_on_chat and request.project_id:
            # Summarize recent pairs (simple heuristic)
            summary = ''
            try:
                mm = get_memory_manager()
                hist = mm.get_project_history(request.project_id)
                tail = hist[-8:] if len(hist) > 8 else hist
                parts = []
                for m in tail:
                    parts.append(f"{m.get('role')}: {(m.get('content') or '')[:120]}")
                summary = " | ".join(parts)[:1000]
            except Exception:
                summary = ''
            # (Telemetry removed)
            b = build_query(request.project_id, summary, request.message)
            if b is None:
                # [BUILDER] failure
                logger.debug(
                    "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                    proj,
                    msg_id,
                    "UNKNOWN",
                    "false",
                    0.00,
                    0,
                    preview,
                )
                # [ROUTE] log with CHITCHAT-like bypass baseline
                logger.debug(
                    "[ROUTE] project_id=%s message_id=%s route=%s namespaces=%s rag_k=%s score_threshold=%.2f",
                    proj,
                    msg_id,
                    "UNKNOWN",
                    [],
                    0,
                    0.0,
                )
                logger.debug("builder unavailable; skipping RAG for this turn")
            else:
                route = (b.get('route') or '').upper()
                do_rag = bool(b.get('rag'))
                conf = float(b.get('confidence') or 0.0)
                topics = b.get('topics') or []
                standalone = b.get('standalone') or request.message
                paraphrases = b.get('paraphrases') or []
                hyde = b.get('hyde') or ''
                # [BUILDER]
                builder_prev = (standalone or preview or "")[:settings.log_preview_max_chars]
                logger.debug(
                    "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                    proj,
                    msg_id,
                    route or "UNKNOWN",
                    "true" if do_rag else "false",
                    conf,
                    len(topics or []),
                    builder_prev,
                )
                # [ROUTE] selection and logging
                try:
                    rcfg = _load_route_config()
                except Exception:
                    rcfg = {}
                rdef = rcfg.get(route or "OTHER") or rcfg.get("OTHER") or {}
                namespaces = rdef.get("namespaces") or []
                rag_k_route = int(rdef.get("rag_k", settings.rag_top_k))
                score_th = float(rdef.get("score_threshold", settings.rag_score_threshold))
                logger.debug(
                    "[ROUTE] project_id=%s message_id=%s route=%s namespaces=%s rag_k=%s score_threshold=%.2f",
                    proj,
                    msg_id,
                    route or "UNKNOWN",
                    namespaces,
                    rag_k_route,
                    score_th,
                )
                set_route(route or "UNKNOWN")
                # Choose a primary namespace (persist the builder route; fallback to general)
                try:
                    if route:
                        primary_ns = (route or "general").lower()
                    else:
                        primary_ns = "general"
                except Exception:
                    primary_ns = "general"
                set_namespace(primary_ns)
                # Strict skip: no retrieval for CHITCHAT or rag=false
                if (not do_rag) or route == 'CHITCHAT':
                    logger.info("Chat: skipping RAG due to route=%s rag=%s", route, do_rag)
                    # (Telemetry removed)
                else:
                    # Check per-project toggle for Daily RAG. If disabled, set daily_top_k=0 to skip daily.
                    daily_enabled = True
                    try:
                        with get_session() as session:
                            p = session.get(Project, request.project_id)
                            if p is not None:
                                daily_enabled = bool(p.daily_rag_enabled)
                    except Exception:
                        daily_enabled = True
                    queries = [standalone]
                    if conf >= settings.builder_confidence_min:
                        queries.extend(paraphrases[:3])
                        if hyde:
                            queries.append(hyde)
                    # Simple multi-query expansion: join variants to widen recall
                    q_join = "\n".join([q for q in queries if q])
                    primary_query = q_join if q_join else (request.message or "")
                    logger.debug(
                        "Chat: performing merged retrieval (daily+main) for project=%s route=%s conf=%.2f queries=%s",
                        request.project_id, route, conf, len(queries)
                    )
                    rc = merge_daily_and_main(
                        project_id=request.project_id,
                        query=primary_query,
                        main_top_k=rag_k_route,
                        main_snippet_max_tokens=settings.rag_snippet_max_tokens,
                        main_threshold=score_th,
                        daily_top_k=(rag_k_route if daily_enabled else 0),
                        daily_threshold=score_th,
                        daily_weight=settings.daily_rag_weight,
                        daily_max_tokens=settings.daily_rag_max_tokens,
                        global_context_max_tokens=settings.rag_context_max_tokens,
                        dedupe_exact=settings.dedupe_exact,
                        dedupe_near=settings.dedupe_near,
                        dedupe_similarity_threshold=settings.dedupe_similarity_threshold,
                        prefer_daily=settings.dedupe_keep_daily,
                        topics=topics,
                        preferred_namespace=None,
                        topic_boost=settings.topic_boost,
                        decision_boost=settings.decision_boost,
                        question_boost=settings.question_boost,
                        route_namespaces=namespaces,
                        namespace_boost=settings.namespace_boost,
                    )
                    # [RETRIEVAL]
                    logger.debug(
                        "[RETRIEVAL] project_id=%s message_id=%s route=%s rag_used=%s main_hits=%s main_avg=%.2f main_threshold=%.2f daily_hits=%s daily_avg=%.2f daily_threshold=%.2f total_hits=%s dedupe_exact_removed=%s dedupe_near_removed=%s",
                        proj,
                        msg_id,
                        route or "UNKNOWN",
                        "true",
                        int(rc.get("main_hits", 0)),
                        float(rc.get("main_avg", 0.0)),
                        float(rc.get("main_threshold", settings.rag_score_threshold)),
                        int(rc.get("daily_hits", 0)),
                        float(rc.get("daily_avg", 0.0)),
                        float(rc.get("daily_threshold", settings.daily_rag_score_threshold)),
                        int(rc.get("total_hits", 0)),
                        int(rc.get("dedupe_exact_removed", 0)),
                        int(rc.get("dedupe_near_removed", 0)),
                    )
                    if rc.get("context_text"):
                        rag_system_prompt = rc["context_text"]
                        logger.debug(f"Chat: injecting merged context tokens={rc.get('tokens_used')}")
                    else:
                        logger.debug("Chat: no merged RAG context injected (empty)")
        # If we have retrieved context, inject RAG guidance into the base system prompt
        if rag_system_prompt:
            try:
                if base_system_prompt:
                    base_system_prompt = (base_system_prompt.rstrip() + "\n\n" + RAG_SYSTEM_PROMPT.strip() + "\n")
                else:
                    base_system_prompt = (RAG_SYSTEM_PROMPT.strip() + "\n")
            except Exception:
                pass
        # Enforce model whitelist if override provided
        if request.model:
            try:
                if request.model not in settings.available_models:
                    raise HTTPException(status_code=400, detail={"error": "Model not allowed"})
            except Exception:
                pass
        # Log LLM request
        try:
            logger.debug(
                "[PROMPT] base_sys_bytes=%s rag_sys_bytes=%s hint_bytes=%s base_sys_preview=\"%s\"",
                len((base_system_prompt or "").encode("utf-8")),
                len((rag_system_prompt or "").encode("utf-8")),
                len((assistant_hint or "").encode("utf-8")),
                ((base_system_prompt or "")[:200].replace("\n", " ")),
            )
        except Exception:
            pass
        llm_logger.log_llm_request(
            model=(request.model or settings.model_name),
            message_length=len(request.message),
            conversation_id=request.conversation_id
        )
        
        logger.debug(f"Chat: model={request.model or 'default'} message_len={len(request.message)} conv_id={request.conversation_id}")
        # Prompt debug snapshot (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            _dump_prompt_debug(
                project_id=request.project_id,
                base_system_prompt=base_system_prompt,
                assistant_hint=assistant_hint,
                rag_system_prompt=rag_system_prompt,
                conversation_history=conversation_history,
                user_prompt=request.message,
                model=(request.model or settings.model_name),
            )
        except Exception:
            pass
        # Generate response using LangChain
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
            if request.project_id:
                memory_manager.append_user_message(request.project_id, request.message)
                memory_manager.append_assistant_message(
                    request.project_id,
                    llm_response["response"],
                    namespace=(primary_ns or "general"),
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
            import tiktoken  # type: ignore
            enc = tiktoken.get_encoding("cl100k_base")
            combined_text = ''
            if conversation_history:
                for msg in conversation_history:
                    combined_text += (msg.get('content') or '') + '\n'
            combined_text += request.message or ''
            # Include the assistant's latest reply
            combined_text += '\n' + (llm_response.get('response') or '')
            context_tokens = len(enc.encode(combined_text))
            if request.project_id:
                set_last_context_tokens(request.project_id, context_tokens)
        except Exception:
            pass
        
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
        clear_message_id()
        try:
            clear_namespace()
        except Exception:
            pass


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint (V3.5).
    Streams model tokens to the client as they arrive.
    """
    settings = get_settings()
    try:
        t0 = time.time()
        msg_id = str(uuid.uuid4())
        set_message_id(msg_id)
        request_logger.log_request(endpoint="/chat/stream", method="POST", user_id=request.conversation_id)
        proj = request.project_id or "Continuum"
        # Build conversation history
        conversation_history = None
        primary_ns = None
        if request.project_id:
            mm = get_memory_manager()
            hist = mm.get_project_history(request.project_id)
            conversation_history = [{"role": m["role"], "content": m["content"]} for m in hist]
        # Load system prompt + personality
        base_system_prompt = None
        assistant_hint = None
        personality_creativity = None
        if request.project_id:
            try:
                base_system_prompt = load_project_system_prompt(request.project_id)
                p = load_project_personality(request.project_id)
                personality_creativity = float(p.get("creativity") or 0.0)
                tone = p.get("tone") or "analytical"
                verb = p.get("verbosity") or "concise"
                fmt = p.get("format") or "markdown"
                domains = p.get("domain_focus") or []
                if not isinstance(domains, list):
                    domains = []
                assistant_hint = f"Follow these preferences: tone={tone}, verbosity={verb}, format={fmt}, domain_focus={domains}. Respond concisely in the chosen format."
            except Exception:
                base_system_prompt = None
                assistant_hint = None
                personality_creativity = None
        # Optional RAG assembly (reuse same logic as /chat but simplified)
        rag_system_prompt = None
        preview = (request.message or "")[:settings.log_preview_max_chars]
        if settings.rag_on_chat and request.project_id:
            try:
                mm = get_memory_manager()
                hist = mm.get_project_history(request.project_id)
                tail = hist[-8:] if len(hist) > 8 else hist
                parts = []
                for m in tail:
                    parts.append(f"{m.get('role')}: {(m.get('content') or '')[:120]}")
                summary = " | ".join(parts)[:1000]
            except Exception:
                summary = ""
            b = build_query(request.project_id, summary, request.message)
            if b:
                route = (b.get('route') or '').upper()
                do_rag = bool(b.get('rag'))
                conf = float(b.get('confidence') or 0.0)
                standalone = b.get('standalone') or request.message
                paraphrases = b.get('paraphrases') or []
                # Select namespaces and build merged context if enabled
                try:
                    rcfg = _load_route_config()
                except Exception:
                    rcfg = {}
                rdef = rcfg.get(route or "OTHER") or rcfg.get("OTHER") or {}
                namespaces = rdef.get("namespaces") or []
                rag_k_route = int(rdef.get("rag_k", settings.rag_top_k))
                score_th = float(rdef.get("score_threshold", settings.rag_score_threshold))
                try:
                    primary_ns = (route or "general").lower() if route else "general"
                except Exception:
                    primary_ns = "general"
                if do_rag and (route != "CHITCHAT"):
                    # daily enabled?
                    daily_enabled = True
                    try:
                        with get_session() as session:
                            p = session.get(Project, request.project_id)
                            if p is not None:
                                daily_enabled = bool(p.daily_rag_enabled)
                    except Exception:
                        daily_enabled = True
                    queries = [standalone]
                    if conf >= settings.builder_confidence_min:
                        queries.extend(paraphrases[:3])
                    q_join = "\n".join([q for q in queries if q])
                    primary_query = q_join if q_join else (request.message or "")
                    rc = merge_daily_and_main(
                        project_id=request.project_id,
                        query=primary_query,
                        main_top_k=rag_k_route,
                        main_snippet_max_tokens=settings.rag_snippet_max_tokens,
                        main_threshold=score_th,
                        daily_top_k=(rag_k_route if daily_enabled else 0),
                        daily_threshold=score_th,
                        daily_weight=settings.daily_rag_weight,
                        daily_max_tokens=settings.daily_rag_max_tokens,
                        global_context_max_tokens=settings.rag_context_max_tokens,
                        dedupe_exact=settings.dedupe_exact,
                        dedupe_near=settings.dedupe_near,
                        dedupe_similarity_threshold=settings.dedupe_similarity_threshold,
                        prefer_daily=settings.dedupe_keep_daily,
                        topics=b.get('topics') or [],
                        preferred_namespace=None,
                        topic_boost=settings.topic_boost,
                        decision_boost=settings.decision_boost,
                        question_boost=settings.question_boost,
                        route_namespaces=namespaces,
                        namespace_boost=settings.namespace_boost,
                    )
                    if rc.get("context_text"):
                        rag_system_prompt = rc["context_text"]
        # If we have retrieved context, inject RAG guidance into the base system prompt
        if rag_system_prompt:
            try:
                if base_system_prompt:
                    base_system_prompt = (base_system_prompt.rstrip() + "\n\n" + RAG_SYSTEM_PROMPT.strip() + "\n")
                else:
                    base_system_prompt = (RAG_SYSTEM_PROMPT.strip() + "\n")
            except Exception:
                pass
        # Persist user immediately
        if request.project_id:
            try:
                get_memory_manager().append_user_message(request.project_id, request.message)
            except Exception:
                pass
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
                            get_memory_manager().append_assistant_message(
                                request.project_id,
                                text,
                                namespace=(primary_ns or "general"),
                            )
                    except Exception:
                        pass
                    # Simulate streaming by yielding characters
                    for ch in text:
                        yield ch
                    yield "\n::event: done\n"
                except Exception as e:
                    yield f"\n[error] {str(e)}\n"
            return StreamingResponse(fake_stream(), media_type="text/plain; charset=utf-8")
        # True streaming via LangChain callback iterator
        # Build messages list
        msgs = []
        if base_system_prompt:
            msgs.append(SystemMessage(content=base_system_prompt))
        if assistant_hint:
            msgs.append(AIMessage(content=assistant_hint))
        if rag_system_prompt:
            msgs.append(SystemMessage(content=rag_system_prompt))
        if conversation_history:
            for m in conversation_history:
                if m.get("role") == "user":
                    msgs.append(HumanMessage(content=m.get("content") or ""))
                elif m.get("role") == "assistant":
                    msgs.append(AIMessage(content=m.get("content") or ""))
        msgs.append(HumanMessage(content=request.message or ""))
        # Prompt debug snapshot (best-effort; no-op unless GENERATE_DEBUG_FILES=true)
        try:
            _dump_prompt_debug(
                project_id=request.project_id,
                base_system_prompt=base_system_prompt,
                assistant_hint=assistant_hint,
                rag_system_prompt=rag_system_prompt,
                conversation_history=conversation_history,
                user_prompt=(request.message or ""),
                model=(request.model or settings.model_name),
            )
        except Exception:
            pass

        # Initialize streaming LLM client (LangChain 0.2.x native astream)
        # Force temperature to 1.0 for maximum compatibility with small models
        llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=(request.model or settings.model_name),
            temperature=1.0,
            model_kwargs={"max_completion_tokens": settings.model_max_tokens},
            streaming=True,
        )

        # Token stream using astream (yields AIMessageChunk with incremental content)
        async def token_stream():
            collected = []
            try:
                async for chunk in llm.astream(msgs):
                    # Only emit actual text content; skip metadata/header chunks
                    piece = getattr(chunk, "content", None)
                    if not piece:
                        piece = getattr(chunk, "delta", None)
                    if isinstance(piece, str) and piece:
                        collected.append(piece)
                        yield piece
                # Signal end of stream
                yield "\n::event: done\n"
            finally:
                # Persist assistant once complete
                try:
                    if request.project_id:
                        full_text = "".join(collected)
                        get_memory_manager().append_assistant_message(
                            request.project_id,
                            full_text,
                            namespace=(primary_ns or "general"),
                        )
                except Exception:
                    pass

        return StreamingResponse(token_stream(), media_type="text/plain; charset=utf-8")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        clear_message_id()
        try:
            clear_namespace()
        except Exception:
            pass

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
