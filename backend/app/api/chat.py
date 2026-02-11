"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

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
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.models import ChatRequest, ChatResponse, ErrorResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..utils.debug_utils import write_debug_file
from ..utils.logging import RequestLogger, LLMLogger, set_message_id, clear_message_id, get_message_id, set_route, clear_route, set_namespace, clear_namespace, get_route
from ..utils.errors import handle_llm_error, log_error_context
from ..core.config import get_settings, get_model_config, compute_per_source_k
from ..core.rag_manager import retrieve_context, merge_daily_and_main
from ..core.route_policy import get_route_policy
from ..core.personality import load_project_system_prompt, load_project_personality
from ..core.daily_rag import start_daily_cache_rebuild
from ..core.database import get_session
from ..core.db_models import Project
from ..core.query_builder import build_query, format_contextual_turn
import os
import json
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

Output constraint:
- Do NOT include similarity scores, snippet numbers, filenames, page numbers, routes, or other retrieval 
metadata in your response unless the user explicitly asks for them.
- Use scores only to guide which retrieved text to rely on.
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
    fname = f"{ts}_prompt_to_execute.txt"
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
        "====== SYSTEM ======\n"
        + (base_system_prompt or "")
        + "\n\n====== ASSISTANT_HINT ======\n"
        + (assistant_hint or "")
        + "\n\n====== (RAG CONTEXT) ======\n"
        + (rag_system_prompt or "")
        + "\n\n====== CONVERSATION HISTORY ======\n"
        + hist_text
        + "\n====== USER PROMPT ======\n"
        + (user_prompt or "")
        + "\n"
    )
    body += f"# total_tokens_estimate: {_estimate_tokens(body + payload_preview)}\n\n"
    body += payload_preview

    write_debug_file(project_id, f"prompts/{fname}", body)


class _ChatPipeline:
    """
    Shared chat pipeline helpers for /chat and /chat/stream.

    Goal: eliminate duplicated logic between streaming and non-streaming endpoints.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    def build_conversation_history(self, project_id: Optional[str]) -> Optional[list[dict]]:
        """Return chronological role/content history suitable for LLM calls."""
        if not project_id:
            return None
        try:
            mm = get_memory_manager()
            hist = mm.get_project_history(project_id)
            # Preserve tagger outputs for downstream builder context assembly.
            return [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "tags_meta_json": m.get("tags_meta_json"),
                    "semantic_handle": m.get("semantic_handle"),
                }
                for m in hist
            ]
        except Exception:
            return None

    def load_project_prompts(self, project_id: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Load base system prompt and personality-derived assistant hint."""
        if not project_id:
            return None, None, None
        try:
            base_system_prompt = load_project_system_prompt(project_id)
            p = load_project_personality(project_id)
            personality_creativity = float(p.get("creativity") or 0.0)
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
            return base_system_prompt, assistant_hint, personality_creativity
        except Exception:
            return None, None, None

    def _build_builder_summary(self, project_id: Optional[str], conversation_history: Optional[list[dict]]) -> str:
        """
        Build a compact summary string for the query builder.
        NOTE: current behavior is lossy truncation; keep stable until replaced.
        """
        try:
            # New behavior: pass ONLY the most recent assistant tag JSON block into the builder.
            # This lets query_builder build "Context/Intent/Type" without using chopped pairs.
            if conversation_history:
                for m in reversed(conversation_history):
                    if (m.get("role") or "").lower() != "assistant":
                        continue
                    tj = m.get("tags_meta_json")
                    if isinstance(tj, str) and tj.strip():
                        return tj.strip()[:2000]

            # Fallback: after sleep flush, ChatMessage history is wiped. Use Project.last_semantic_handle
            # to seed the builder summary with a minimal JSON block containing only semantic_handle.
            if project_id:
                try:
                    with get_session() as session:
                        p = session.get(Project, project_id)
                        h = getattr(p, "last_semantic_handle", None) if p is not None else None
                        if isinstance(h, str) and h.strip():
                            return json.dumps({"semantic_handle": h.strip()}, ensure_ascii=False)[:2000]
                except Exception:
                    pass

            return ""
        except Exception:
            return ""

    def previous_pair_text(self, conversation_history: Optional[list[dict]]) -> Optional[str]:
        """Immediately previous active pair text (User/Assistant), or None."""
        if not conversation_history:
            return None
        try:
            # Find the most recent assistant message and the nearest preceding user.
            last_asst_idx = None
            for i in range(len(conversation_history) - 1, -1, -1):
                if (conversation_history[i].get("role") or "").lower() == "assistant":
                    last_asst_idx = i
                    break
            if last_asst_idx is None:
                return None
            user_idx = None
            for j in range(last_asst_idx - 1, -1, -1):
                if (conversation_history[j].get("role") or "").lower() == "user":
                    user_idx = j
                    break
            if user_idx is None:
                return None
            u = conversation_history[user_idx].get("content") or ""
            a = conversation_history[last_asst_idx].get("content") or ""
            return f"User: {u}\nAssistant: {a}"
        except Exception:
            return None

    def _daily_enabled(self, project_id: str) -> bool:
        try:
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is not None:
                    return bool(p.daily_rag_enabled)
        except Exception:
            pass
        return True

    def compute_rag_context(
        self,
        *,
        project_id: Optional[str],
        message: str,
        preview: str,
        msg_id: str,
        conversation_history: Optional[list[dict]],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Run builder + merged retrieval when enabled.
        Returns (rag_system_prompt, primary_ns).
        """
        rag_system_prompt: Optional[str] = None
        primary_ns: Optional[str] = None
        if (not self.settings.rag_on_chat) or (not project_id):
            return None, None

        summary = self._build_builder_summary(project_id, conversation_history)
        b = build_query(project_id, summary, message)
        if b is None:
            # [BUILDER] failure
            try:
                logger.debug(
                    "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                    project_id,
                    msg_id,
                    "UNKNOWN",
                    "false",
                    0.00,
                    0,
                    preview,
                )
                logger.debug(
                    "[ROUTE] project_id=%s message_id=%s route=%s namespaces=%s",
                    project_id,
                    msg_id,
                    "UNKNOWN",
                    [],
                )
            except Exception:
                pass
            logger.debug("builder unavailable; skipping RAG for this turn")
            return None, None

        route = (b.get("route") or "").upper()
        # Route-only classifier: no rag/confidence/topics required.
        conf = float(b.get("confidence") or 0.0) if isinstance(b.get("confidence"), (int, float, str)) else 0.0
        topics = b.get("topics") or []
        # Builder is still run for categorization/route/topics, but its rewritten queries
        # (standalone/paraphrases/hyde) must NOT change the canonical retrieval query.
        standalone = b.get("standalone") or message
        paraphrases = b.get("paraphrases") or []
        hyde = b.get("hyde") or ""

        # [BUILDER]
        try:
            builder_prev = (standalone or preview or "")[:self.settings.log_preview_max_chars]
            logger.debug(
                "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                project_id,
                msg_id,
                route or "UNKNOWN",
                "true",
                conf,
                len(topics or []),
                builder_prev,
            )
        except Exception:
            pass

        try:
            logger.debug(
                "[ROUTE] project_id=%s message_id=%s route=%s base_top_k=%s retrieval_multiplier=%.2f",
                project_id,
                msg_id,
                route or "UNKNOWN",
                int(self.settings.base_top_k),
                float(self.settings.retrieval_multiplier),
            )
        except Exception:
            pass

        set_route(route or "UNKNOWN")
        try:
            primary_ns = (route or "general").lower() if route else "general"
        except Exception:
            primary_ns = "general"
        set_namespace(primary_ns)

        # DELTA-A.4.3: route_policy.json is validated at startup and cached for process lifetime.
        pol = get_route_policy(route or "OTHER")
        mult_val = float(pol.retrieval_multiplier)
        max_keep = int(pol.max_keep)
        per_source_k = compute_per_source_k(int(self.settings.base_top_k), float(mult_val))
        if per_source_k <= 0:
            logger.info("Chat: skipping RAG due to route=%s per_source_k=%s", route, per_source_k)
            return None, primary_ns

        daily_enabled = self._daily_enabled(project_id)

        # Canonical retrieval query: use the exact contextual query string we built
        # (<user_prompt> + optional Context/Intent/Type), unchanged by builder rewrites.
        # NOTE: `summary` is the tags_meta_json block from _build_builder_summary().
        primary_query = format_contextual_turn(message, summary)
        queries = [primary_query] if primary_query else []

        # Debug: persist the actual RAG query string used for retrieval.
        # Only emit when retrieval actually runs (we are past rag=false / CHITCHAT checks).
        try:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            fname = f"{ts}_rag_query.txt"
            body = (
                f"# timestamp: {ts}\n"
                f"# project_id: {project_id}\n"
                f"# route: {route or 'UNKNOWN'}\n"
                f"# rag: true\n"
                f"# base_top_k: {int(self.settings.base_top_k)}\n"
                f"# retrieval_multiplier: {mult_val}\n"
                f"# per_source_k: {int(per_source_k)}\n"
                f"# max_keep: {max_keep}\n"
                f"# queries_count: {len([q for q in queries if q])}\n"
                "\n"
                "====== USER PROMPT ======\n"
                f"{message or ''}\n"
                "\n"
                "====== RAG Query String ======\n"
                f"{primary_query}\n"
            )
            write_debug_file(project_id, f"prompts/{fname}", body)
        except Exception:
            pass

        logger.debug(
            "Chat: performing merged retrieval (daily+main) for project=%s route=%s conf=%.2f queries=%s",
            project_id,
            route,
            conf,
            len(queries),
        )

        rc = merge_daily_and_main(
            project_id=project_id,
            query=primary_query,
            daily_enabled=bool(daily_enabled),
            max_keep=int(max_keep),
            route=(route or "OTHER"),
            per_source_k_override=int(per_source_k),
        )

        try:
            logger.debug(
                "[RETRIEVAL] project_id=%s message_id=%s route=%s rag_used=%s per_source_k=%s max_keep=%s ordered=%s kept=%s main_hits=%s main_avg=%.2f daily_hits=%s daily_avg=%.2f total_hits=%s",
                project_id,
                msg_id,
                route or "UNKNOWN",
                "true",
                int(per_source_k),
                int(max_keep),
                int(rc.get("ordered_candidates", 0)),
                int(rc.get("kept_candidates", 0)),
                int(rc.get("main_hits", 0)),
                float(rc.get("main_avg", 0.0)),
                int(rc.get("daily_hits", 0)),
                float(rc.get("daily_avg", 0.0)),
                int(rc.get("total_hits", 0)),
            )
        except Exception:
            pass

        if rc.get("context_text"):
            rag_system_prompt = rc["context_text"]
            logger.debug("Chat: injecting merged context tokens=%s", rc.get("tokens_used"))
        else:
            logger.debug("Chat: no merged RAG context injected (empty)")

        return rag_system_prompt, primary_ns

    def apply_rag_guidance(self, base_system_prompt: Optional[str], rag_system_prompt: Optional[str]) -> Optional[str]:
        """Append guidance to system prompt only when RAG context exists."""
        if not rag_system_prompt:
            return base_system_prompt
        try:
            if base_system_prompt:
                return base_system_prompt.rstrip() + "\n\n" + RAG_SYSTEM_PROMPT.strip() + "\n"
            return RAG_SYSTEM_PROMPT.strip() + "\n"
        except Exception:
            return base_system_prompt

    def enforce_model_whitelist(self, requested_model: Optional[str]) -> None:
        if not requested_model:
            return
        if requested_model not in self.settings.available_models:
            raise HTTPException(status_code=400, detail={"error": "Model not allowed"})

    def build_llm_messages(
        self,
        *,
        base_system_prompt: Optional[str],
        assistant_hint: Optional[str],
        rag_system_prompt: Optional[str],
        conversation_history: Optional[list[dict]],
        user_message: str,
    ) -> list:
        msgs: list = []
        if base_system_prompt:
            msgs.append(SystemMessage(content=base_system_prompt))
        if assistant_hint:
            msgs.append(AIMessage(content=assistant_hint))
        if rag_system_prompt:
            msgs.append(SystemMessage(content=rag_system_prompt))
        if conversation_history:
            for m in conversation_history:
                if (m.get("role") or "").lower() == "user":
                    msgs.append(HumanMessage(content=m.get("content") or ""))
                elif (m.get("role") or "").lower() == "assistant":
                    msgs.append(AIMessage(content=m.get("content") or ""))
        msgs.append(HumanMessage(content=user_message or ""))
        return msgs

    def persist_user(self, project_id: Optional[str], message: str) -> None:
        if not project_id:
            return
        try:
            get_memory_manager().append_user_message(project_id, message)
        except Exception:
            pass

    def persist_assistant(
        self,
        project_id: Optional[str],
        message: str,
        namespace: Optional[str],
        *,
        user_text_for_tagging: Optional[str] = None,
        previous_pair_text_for_tagging: Optional[str] = None,
    ) -> None:
        if not project_id:
            return
        try:
            get_memory_manager().append_assistant_message(
                project_id,
                message,
                namespace=(namespace or "general"),
                user_text_for_tagging=user_text_for_tagging,
                previous_pair_text_for_tagging=previous_pair_text_for_tagging,
            )
        except Exception:
            pass


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

        pipeline = _ChatPipeline(settings)
        memory_manager = get_memory_manager() if request.project_id else None
        conversation_history = pipeline.build_conversation_history(request.project_id)
        base_system_prompt, assistant_hint, personality_creativity = pipeline.load_project_prompts(request.project_id)
        rag_system_prompt, primary_ns = pipeline.compute_rag_context(
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
            if request.project_id and memory_manager is not None:
                prev_pair = pipeline.previous_pair_text(conversation_history)
                memory_manager.append_user_message(request.project_id, request.message)
                memory_manager.append_assistant_message(
                    request.project_id,
                    llm_response["response"],
                    namespace=(primary_ns or "general"),
                    user_text_for_tagging=request.message,
                    previous_pair_text_for_tagging=prev_pair,
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

        pipeline = _ChatPipeline(settings)
        conversation_history = pipeline.build_conversation_history(request.project_id)
        base_system_prompt, assistant_hint, personality_creativity = pipeline.load_project_prompts(request.project_id)
        rag_system_prompt, primary_ns = pipeline.compute_rag_context(
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
                                (primary_ns or "general"),
                                user_text_for_tagging=(request.message or ""),
                                previous_pair_text_for_tagging=prev_pair,
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
        msgs = pipeline.build_llm_messages(
            base_system_prompt=base_system_prompt,
            assistant_hint=assistant_hint,
            rag_system_prompt=rag_system_prompt,
            conversation_history=conversation_history,
            user_message=(request.message or ""),
        )
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

        # Token stream using astream (yields AIMessageChunk with incremental content)
        async def token_stream():
            collected = []
            try:
                # Initialize streaming LLM client (LangChain 0.2.x native astream)
                # Try with temperature=1.0, but some models reject the temperature parameter entirely.
                model_name = (request.model or settings.model_name)
                llm = ChatOpenAI(
                    api_key=settings.openai_api_key,
                    model=model_name,
                    temperature=1.0,
                    model_kwargs={"max_completion_tokens": settings.model_max_tokens},
                    streaming=True,
                )
                yielded_any = False
                try:
                    async for chunk in llm.astream(msgs):
                        # Only emit actual text content; skip metadata/header chunks
                        piece = getattr(chunk, "content", None)
                        if not piece:
                            piece = getattr(chunk, "delta", None)
                        if isinstance(piece, str) and piece:
                            yielded_any = True
                            collected.append(piece)
                            yield piece
                except Exception as e:
                    msg = str(e).lower()
                    if (not yielded_any) and ("temperature" in msg or "unsupported_value" in msg or "invalid_request_error" in msg):
                        llm2 = ChatOpenAI(
                            api_key=settings.openai_api_key,
                            model=model_name,
                            model_kwargs={"max_completion_tokens": settings.model_max_tokens},
                            streaming=True,
                        )
                        async for chunk in llm2.astream(msgs):
                            piece = getattr(chunk, "content", None)
                            if not piece:
                                piece = getattr(chunk, "delta", None)
                            if isinstance(piece, str) and piece:
                                collected.append(piece)
                                yield piece
                    else:
                        raise
                    # Only emit actual text content; skip metadata/header chunks
                # Signal end of stream
                yield "\n::event: done\n"
            finally:
                # Persist assistant once complete
                try:
                    if request.project_id:
                        full_text = "".join(collected)
                        pipeline.persist_assistant(
                            request.project_id,
                            full_text,
                            (primary_ns or "general"),
                            user_text_for_tagging=(request.message or ""),
                            previous_pair_text_for_tagging=prev_pair,
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
