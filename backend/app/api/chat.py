"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

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
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.models import ChatRequest, ChatResponse, ErrorResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..llm_model.factory import get_llm_client
from ..core.memory import get_memory_manager, set_last_context_tokens
from ..utils.debug_utils import write_debug_file
from ..utils.logging import RequestLogger, LLMLogger, set_message_id, clear_message_id, get_message_id, set_route, clear_route, set_namespace, clear_namespace, get_route
from ..utils.errors import handle_llm_error, log_error_context
from ..core.config import get_settings, compute_per_source_k
from ..rag.manager import retrieve_context, merge_daily_and_main
from ..core.route_policy import get_route_policy
from ..core.personality import load_project_system_prompt, load_project_personality
from ..rag.daily_store import start_daily_cache_rebuild
from ..core.database import get_session
from ..core.db_models import Project
from ..core.query_builder import build_query, format_contextual_turn
from ..tracking import get_instrumentation
import os
import json

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()
_TURN_SEQ = 0
_TURN_SEQ_LOCK = threading.Lock()

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


def _estimate_message_tokens(messages: list) -> int:
    """Best-effort token estimate over structured message list."""
    try:
        text = "\n".join(str((m.get("content") or "")) for m in (messages or []) if isinstance(m, dict))
        return int(_estimate_tokens(text))
    except (AttributeError, TypeError, ValueError):
        return 0


def _next_turn_id() -> int:
    global _TURN_SEQ
    with _TURN_SEQ_LOCK:
        _TURN_SEQ += 1
        return int(_TURN_SEQ)

def _dump_prompt_debug(
    *,
    project_id: Optional[str],
    base_system_prompt: Optional[str],
    assistant_hint: Optional[str],
    rag_system_prompt: Optional[str],
    conversation_history: Optional[list[dict]],
    user_prompt: Optional[str],
    model: Optional[str],
    msgs: Optional[list] = None,
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
    except Exception as exc:
        logger.debug("chat.prompt_debug failed reading route; detail=%s", exc)
        route = None
    rag_used = bool(rag_system_prompt)
    _ = msgs  # Reserved for future exact-payload debug variants.

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
    # Estimate tokens over the whole formatted dump (best-effort).
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
                    "namespace": m.get("namespace"),
                    "keep": m.get("keep"),
                }
                for m in hist
            ]
        except (AttributeError, TypeError, ValueError):
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
        except (KeyError, TypeError, ValueError):
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
                except Exception as exc:
                    logger.warning(
                        "chat.builder_summary failed fallback lookup project_id=%s detail=%s",
                        project_id,
                        exc,
                    )

            return ""
        except Exception:
            return ""

    def previous_pair_text(self, conversation_history: Optional[list[dict]]) -> Optional[str]:
        """Immediately previous active pair text + prior tags, or None."""
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
            asst_msg = conversation_history[last_asst_idx] or {}
            a = asst_msg.get("content") or ""

            ns = str(asst_msg.get("namespace") or "other").strip().lower()
            keep = bool(asst_msg.get("keep", False))
            topics = ""
            intent = ""
            tag_type = ""
            semantic_handle = ""
            try:
                tj = asst_msg.get("tags_meta_json")
                if isinstance(tj, str) and tj.strip():
                    parsed = json.loads(tj)
                    if isinstance(parsed, dict):
                        topics = str(parsed.get("topics", "") or "")
                        intent = str(parsed.get("intent", "") or "")
                        tag_type = str(parsed.get("type", "") or "")
                        semantic_handle = str(parsed.get("semantic_handle", "") or "")
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.debug("chat.previous_pair_text failed parsing tags_meta_json", exc_info=True)

            return (
                f"#route: {ns}\n"
                f"#keep: {str(keep).lower()}\n"
                f"#topics: {topics}\n"
                f"#intent: {intent}\n"
                f"#type: {tag_type}\n"
                f"#semantic_handle: {semantic_handle}\n"
                f"User: {u}\n"
                f"Assistant: {a}"
            )
        except Exception:
            return None

    def _daily_enabled(self, project_id: str) -> bool:
        try:
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is not None:
                    return bool(p.daily_rag_enabled)
        except (OSError, TypeError, ValueError):
            logger.debug("chat.daily_enabled lookup failed project_id=%s", project_id, exc_info=True)
        return True

    def compute_rag_context(
        self,
        *,
        project_id: Optional[str],
        message: str,
        preview: str,
        msg_id: str,
        conversation_history: Optional[list[dict]],
    ) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
        """
        Run builder + merged retrieval when enabled.
        Returns (rag_system_prompt, primary_ns, rag_metrics).
        """
        rag_system_prompt: Optional[str] = None
        primary_ns: Optional[str] = None
        rag_metrics: Dict[str, Any] = {
            "route": "OTHER",
            "rag_enabled": False,
            "retrieved_count": 0,
            "kept_count": 0,
            "expanded_unique_chunks_after_merge": 0,
            "rag_tokens_injected_est": 0,
            "final_context_clipped": False,
        }
        if (not self.settings.rag_on_chat) or (not project_id):
            return None, None, rag_metrics

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
                logger.debug("chat.builder debug logging failed project_id=%s", project_id, exc_info=True)
            logger.debug("builder unavailable; skipping RAG for this turn")
            return None, None, rag_metrics

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
        except Exception as exc:
            logger.debug("chat.builder route logging failed project_id=%s detail=%s", project_id, exc)

        try:
            logger.debug(
                "[ROUTE] project_id=%s message_id=%s route=%s base_top_k=%s retrieval_multiplier=%.2f",
                project_id,
                msg_id,
                route or "UNKNOWN",
                int(self.settings.base_top_k),
                float(self.settings.retrieval_multiplier),
            )
        except Exception as exc:
            logger.warning(
                "chat.rag_query_debug_write failed project_id=%s message_id=%s detail=%s",
                project_id,
                msg_id,
                exc,
            )

        set_route(route or "UNKNOWN")
        try:
            primary_ns = (route or "other").lower() if route else "other"
        except Exception:
            primary_ns = "other"
        set_namespace(primary_ns)
        rag_metrics["route"] = str(route or "OTHER")

        # route_policy.json is validated at startup and cached for process lifetime.
        pol = get_route_policy(route or "OTHER")
        mult_val = float(pol.retrieval_multiplier)
        max_keep = int(pol.max_keep)
        per_source_k = compute_per_source_k(int(self.settings.base_top_k), float(mult_val))
        if per_source_k <= 0:
            logger.info("Chat: skipping RAG due to route=%s per_source_k=%s", route, per_source_k)
            return None, primary_ns, rag_metrics

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
        except Exception as exc:
            logger.debug(
                "chat.retrieval metrics logging failed project_id=%s message_id=%s detail=%s",
                project_id,
                msg_id,
                exc,
            )

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
        except Exception as exc:
            logger.warning(
                "chat.prompt_assembly instrumentation failed project_id=%s detail=%s",
                project_id,
                exc,
            )

        if rc.get("context_text"):
            rag_system_prompt = rc["context_text"]
            logger.debug("Chat: injecting merged context tokens=%s", rc.get("tokens_used"))
        else:
            logger.debug("Chat: no merged RAG context injected (empty)")

        rag_metrics.update(
            {
                "route": str(route or "OTHER"),
                "rag_enabled": True,
                "retrieved_count": int(rc.get("ordered_candidates", 0) or 0),
                "kept_count": int(rc.get("selected_candidates", 0) or 0),
                "expanded_unique_chunks_after_merge": int(rc.get("expanded_unique_chunks_after_merge", 0) or 0),
                "rag_tokens_injected_est": int(rc.get("tokens_used", 0) or 0),
            }
        )
        return rag_system_prompt, primary_ns, rag_metrics

    def apply_rag_guidance(self, base_system_prompt: Optional[str], rag_system_prompt: Optional[str]) -> Optional[str]:
        """Append guidance to system prompt only when RAG context exists."""
        if not rag_system_prompt:
            return base_system_prompt
        try:
            if base_system_prompt:
                return base_system_prompt.rstrip() + "\n\n" + RAG_SYSTEM_PROMPT.strip() + "\n"
            return RAG_SYSTEM_PROMPT.strip() + "\n"
        except (AttributeError, TypeError):
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
            msgs.append({"role": "system", "content": base_system_prompt})
        if assistant_hint:
            msgs.append({"role": "assistant", "content": assistant_hint})
        if rag_system_prompt:
            msgs.append({"role": "system", "content": rag_system_prompt})
        if conversation_history:
            for m in conversation_history:
                if (m.get("role") or "").lower() == "user":
                    msgs.append({"role": "user", "content": m.get("content") or ""})
                elif (m.get("role") or "").lower() == "assistant":
                    msgs.append({"role": "assistant", "content": m.get("content") or ""})
        msgs.append({"role": "user", "content": user_message or ""})
        try:
            get_instrumentation().record_stage(
                "prompt_assembly",
                {
                    "module": "chat_stream",
                    "prompt_system_tokens_est": int(_estimate_tokens(base_system_prompt or "")),
                    "prompt_history_tokens_est": int(
                        _estimate_tokens("\n".join(str((m.get("content") or "")) for m in (conversation_history or [])))
                    ),
                    "prompt_rag_tokens_est": int(_estimate_tokens(rag_system_prompt or "")),
                    "prompt_profile_tokens_est": int(_estimate_tokens(assistant_hint or "")),
                    "prompt_other_tokens_est": int(_estimate_tokens(user_message or "")),
                    "message_count": int(len(msgs)),
                },
            )
        except Exception as exc:
            logger.warning(
                "chat.prompt_assembly instrumentation failed; operation=record_stage module=chat_stream detail=%s",
                exc,
            )
        return msgs

    def persist_user(self, project_id: Optional[str], message: str) -> None:
        if not project_id:
            return
        try:
            get_memory_manager().append_user_message(project_id, message)
        except Exception as exc:
            logger.warning(
                "chat.persist_user failed; operation=append_user_message project_id=%s detail=%s",
                project_id,
                exc,
                exc_info=True,
            )

    def persist_assistant(
        self,
        project_id: Optional[str],
        message: str,
        namespace: Optional[str],
        *,
        user_text_for_tagging: Optional[str] = None,
        previous_pair_text_for_tagging: Optional[str] = None,
        forget: bool = False,
        skip_tagger: bool = False,
    ) -> None:
        if not project_id:
            return
        try:
            if bool(forget) or bool(skip_tagger):
                logger.debug(
                    "[CHITCHAT] project_id=%s namespace=%s forget=%s skip_tagger=%s",
                    project_id,
                    str(namespace or "other").lower(),
                    bool(forget),
                    bool(skip_tagger),
                )
            get_memory_manager().append_assistant_message(
                project_id,
                message,
                namespace=(namespace or "other"),
                user_text_for_tagging=user_text_for_tagging,
                previous_pair_text_for_tagging=previous_pair_text_for_tagging,
                forget=bool(forget),
                skip_tagger=bool(skip_tagger),
            )
        except Exception as exc:
            logger.warning(
                "chat.persist_assistant failed; operation=append_assistant_message project_id=%s detail=%s",
                project_id,
                exc,
                exc_info=True,
            )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint handles the core chat functionality using the shared LLM factory.
    It supports conversation history and project context (stubbed for V4).
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

        pipeline = _ChatPipeline(settings)
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
            _dump_prompt_debug(
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
    Streaming chat endpoint (V3.5).
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

        pipeline = _ChatPipeline(settings)
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
            _dump_prompt_debug(
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
                    prompt_tokens_est = int(_estimate_message_tokens(msgs))
                    completion_tokens_est = int(_estimate_tokens(full_text))
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
