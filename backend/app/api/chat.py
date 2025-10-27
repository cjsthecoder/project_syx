"""
Chat API endpoint for Morpheus AGI Chatbot Framework.

This module provides the main chat functionality with LangChain integration.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from ..core.models import ChatRequest, ChatResponse, ErrorResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..utils.logging import RequestLogger, LLMLogger
from ..utils.errors import handle_llm_error, log_error_context
from ..core.config import get_settings
from ..core.rag_manager import retrieve_context, merge_daily_and_main
from ..core.database import get_session
from ..core.db_models import Project
from ..core.query_builder import build_query

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint handles the core chat functionality using LangChain ChatOpenAI.
    It supports conversation history and project context (stubbed for V4).
    """
    try:
        # Log the incoming request
        request_logger.log_request(
            endpoint="/chat",
            method="POST",
            user_id=request.conversation_id
        )
        
        settings = get_settings()
        
        # Build conversation history from per-project working memory (V2.2)
        conversation_history = None
        if request.project_id:
            memory_manager = get_memory_manager()
            proj_msgs = memory_manager.get_project_history(request.project_id)
            # chronological messages already; map to role/content for LLM
            conversation_history = [{"role": m["role"], "content": m["content"]} for m in proj_msgs]
        
        # Optional RAG retrieval (V2.3.1: builder + daily/main merge)
        system_prompt = None
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
            b = build_query(request.project_id, summary, request.message)
            if b is None:
                logger.info("builder unavailable; skipping RAG for this turn")
            else:
                route = (b.get('route') or '').upper()
                do_rag = bool(b.get('rag'))
                conf = float(b.get('confidence') or 0.0)
                topics = b.get('topics') or []
                standalone = b.get('standalone') or request.message
                paraphrases = b.get('paraphrases') or []
                hyde = b.get('hyde') or ''
                logger.info(
                    "builder result route=%s rag=%s conf=%.2f topics=%s standalone=%s paraphrases=%s",
                    route, do_rag, conf,
                    ",".join(map(str, topics[:5])),
                    (standalone[:120] + ("…" if len(standalone) > 120 else "")),
                    len(paraphrases or []),
                )
                # Strict skip: no retrieval for CHITCHAT or rag=false
                if (not do_rag) or route == 'CHITCHAT':
                    logger.info("Chat: skipping RAG due to route=%s rag=%s", route, do_rag)
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
                    preferred_ns = None
                    if route in ('JIRA','CODE','DOCS'):
                        preferred_ns = route.lower()
                    primary_query = queries[0] if queries else request.message
                    logger.debug(
                        "Chat: performing merged retrieval (daily+main) for project=%s route=%s conf=%.2f queries=%s",
                        request.project_id, route, conf, len(queries)
                    )
                    rc = merge_daily_and_main(
                        project_id=request.project_id,
                        query=primary_query,
                        main_top_k=settings.rag_top_k,
                        main_snippet_max_tokens=settings.rag_snippet_max_tokens,
                        main_threshold=settings.rag_score_threshold,
                        daily_top_k=(settings.daily_rag_k if daily_enabled else 0),
                        daily_threshold=settings.daily_rag_score_threshold,
                        daily_weight=settings.daily_rag_weight,
                        daily_max_tokens=settings.daily_rag_max_tokens,
                        global_context_max_tokens=settings.rag_context_max_tokens,
                        dedupe_exact=settings.dedupe_exact,
                        dedupe_near=settings.dedupe_near,
                        dedupe_similarity_threshold=settings.dedupe_similarity_threshold,
                        prefer_daily=settings.dedupe_keep_daily,
                        topics=topics,
                        preferred_namespace=preferred_ns,
                        topic_boost=settings.topic_boost,
                        decision_boost=settings.decision_boost,
                        question_boost=settings.question_boost,
                    )
                    if rc.get("context_text"):
                        system_prompt = rc["context_text"]
                        logger.debug(f"Chat: injecting merged context tokens={rc.get('tokens_used')}")
                    else:
                        logger.debug("Chat: no merged RAG context injected (empty)")
        
        # Log LLM request
        llm_logger.log_llm_request(
            model="gpt-5",  # Will be dynamic in future
            message_length=len(request.message),
            conversation_id=request.conversation_id
        )
        
        logger.debug(f"Chat: model={request.model or 'default'} message_len={len(request.message)} conv_id={request.conversation_id}")
        # Generate response using LangChain
        llm_response = generate_chat_response(
            message=request.message,
            conversation_history=conversation_history,
            system_prompt=system_prompt,
            override_model=request.model
        )
        
        # Check if LLM response was successful
        if not llm_response.get("success", False):
            raise Exception(llm_response.get("error", "Unknown LLM error"))
        
        # Log LLM response
        llm_logger.log_llm_response(
            model=llm_response.get("llm_model", "gpt-5"),
            response_length=len(llm_response["response"]),
            tokens_used=llm_response.get("tokens_used"),
            conversation_id=request.conversation_id
        )
        logger.debug(f"Chat: response_len={len(llm_response['response'])} tokens_used={llm_response.get('tokens_used')} model={llm_response.get('llm_model')}")
        
        # Persist user and assistant messages (project-scoped working memory)
        try:
            if request.project_id:
                memory_manager.append_user_message(request.project_id, request.message)
                memory_manager.append_assistant_message(request.project_id, llm_response["response"])
        except Exception:
            pass
        
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
        request_logger.log_response(
            endpoint="/chat",
            status_code=200,
            response_time=0.0,  # Would be calculated in real implementation
            user_id=request.conversation_id
        )
        
        return response
        
    except Exception as e:
        # Log error
        request_logger.log_error(
            endpoint="/chat",
            error=e,
            user_id=request.conversation_id
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
