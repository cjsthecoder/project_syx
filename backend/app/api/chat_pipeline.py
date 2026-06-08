"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Chat pipeline helpers extracted from chat routes.
"""


import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

from ..core.config import compute_per_source_k
from ..core.database import get_session
from ..core.db_models import Project
from ..core.memory import get_memory_manager
from ..core.personality import load_project_personality, load_project_system_prompt
from ..core.query_builder import build_query, format_contextual_turn
from ..core.route_policy import RoutePolicy, get_route_policy
from ..rag.manager import merge_daily_and_main
from ..tracking import get_instrumentation
from ..utils.debug_utils import write_debug_file
from ..utils.logging import set_namespace, set_route
from .chat_prompting import RAG_SYSTEM_PROMPT, estimate_message_tokens, estimate_tokens

logger = logging.getLogger(__name__)


class ChatPipeline:
    """
    Shared chat pipeline helpers for /chat and /chat/stream.

    Goal: eliminate duplicated logic between streaming and non-streaming endpoints.
    """

    def __init__(self, settings) -> None:
        """Initialize the pipeline with runtime settings.

        Args:
            settings: Application settings object providing RAG, retrieval,
                model, and logging configuration used throughout the pipeline.
        """
        self.settings = settings

    def build_conversation_history(self, project_id: Optional[str]) -> Optional[list[dict]]:
        """Load project working memory as a list of role/content message dicts.

        Args:
            project_id: Project whose history to load; ``None`` for an
                anonymous turn with no history.

        Returns:
            A list of message dicts (role, content, and tagging metadata), or
            ``None`` when there is no project or loading fails.
        """
        if not project_id:
            return None
        try:
            mm = get_memory_manager()
            hist = mm.get_project_history(project_id)
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
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("chat.pipeline history load failed project_id=%s detail=%s", project_id, exc)
            return None

    def load_project_prompts(self, project_id: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Load the project's system prompt, assistant hint, and creativity.

        Builds an assistant-hint string from the project's personality
        preferences (tone, verbosity, format, domain focus).

        Args:
            project_id: Project to load prompts for; ``None`` for no project.

        Returns:
            Tuple of ``(base_system_prompt, assistant_hint,
            personality_creativity)``; all ``None`` when there is no project
            or loading fails.
        """
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
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("chat.pipeline prompt load failed project_id=%s detail=%s", project_id, exc)
            return None, None, None

    def _build_builder_summary(self, project_id: Optional[str], conversation_history: Optional[list[dict]]) -> str:
        """Return a short context summary for the query builder.

        Prefers the most recent assistant tag metadata; falls back to the
        project's stored semantic handle.

        Args:
            project_id: Project used for the semantic-handle fallback.
            conversation_history: Prior turns scanned for the latest assistant
                tag metadata.

        Returns:
            A summary string for the builder, or an empty string when no
            summary is available.
        """
        try:
            direct_summary = self._latest_assistant_tags_meta(conversation_history)
            if direct_summary:
                return direct_summary
            return self._project_semantic_handle_summary(project_id)
        except Exception as exc:
            logger.warning("chat.pipeline builder summary failed project_id=%s detail=%s", project_id, exc)
            return ""

    def _latest_assistant_tags_meta(self, conversation_history: Optional[list[dict]]) -> str:
        """Return the most recent assistant message's tag metadata JSON (capped at 2000 chars).

        Args:
            conversation_history: Prior turns scanned newest-first for an
                assistant message carrying ``tags_meta_json``.

        Returns:
            The latest assistant tag metadata JSON string truncated to 2000
            characters, or an empty string when none is found.
        """
        if not conversation_history:
            return ""
        for msg in reversed(conversation_history):
            if (msg.get("role") or "").lower() != "assistant":
                continue
            tags_meta_json = msg.get("tags_meta_json")
            if isinstance(tags_meta_json, str) and tags_meta_json.strip():
                return tags_meta_json.strip()[:2000]
        return ""

    def _project_semantic_handle_summary(self, project_id: Optional[str]) -> str:
        """Return the project's stored semantic handle as a JSON summary string (capped at 2000 chars).

        Args:
            project_id: Project whose ``last_semantic_handle`` is looked up;
                ``None`` yields an empty string.

        Returns:
            A ``{"semantic_handle": ...}`` JSON string truncated to 2000
            characters, or an empty string when unavailable or on lookup
            failure.
        """
        if not project_id:
            return ""
        try:
            with get_session() as session:
                project = session.get(Project, project_id)
                handle = getattr(project, "last_semantic_handle", None) if project is not None else None
                if isinstance(handle, str) and handle.strip():
                    return json.dumps({"semantic_handle": handle.strip()}, ensure_ascii=False)[:2000]
        except Exception as exc:
            logger.warning(
                "chat.builder_summary failed fallback lookup project_id=%s detail=%s",
                project_id,
                exc,
            )
        return ""

    def previous_pair_text(self, conversation_history: Optional[list[dict]]) -> Optional[str]:
        """Return the most recent user/assistant pair formatted for tagging context.

        Locates the latest assistant turn and its preceding user turn, then
        renders them together with the assistant's routing/tag metadata
        (route, keep, topics, intent, type, semantic handle).

        Args:
            conversation_history: Prior turns to scan for the latest complete
                user/assistant pair.

        Returns:
            The formatted pair text, or ``None`` when a complete pair cannot
            be found.
        """
        if not conversation_history:
            return None
        try:
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
        except Exception as exc:
            logger.warning("chat.pipeline previous_pair_text failed detail=%s", exc, exc_info=True)
            return None

    def _daily_enabled(self, project_id: str) -> bool:
        """Return whether daily RAG is enabled for the project (defaults to True on lookup failure).

        Args:
            project_id: Project whose ``daily_rag_enabled`` flag is read.

        Returns:
            The project's daily-RAG setting, or ``True`` when the project is
            missing or the lookup fails.
        """
        try:
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is not None:
                    return bool(p.daily_rag_enabled)
        except (OSError, TypeError, ValueError):
            logger.debug("chat.daily_enabled lookup failed project_id=%s", project_id, exc_info=True)
        return True

    @staticmethod
    def _initial_rag_metrics() -> Dict[str, Any]:
        """Return the default RAG metrics dict for a turn (RAG not yet run).

        Returns:
            A metrics dict with the route defaulted to ``OTHER`` and all counts
            zeroed, matching the shape returned by ``compute_rag_context``.
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

    def _classify_route(
        self,
        *,
        project_id: str,
        message: str,
        summary: str,
        preview: str,
        msg_id: str,
    ) -> Optional[str]:
        """Classify a turn into a retrieval route via the query builder.

        Runs the builder and logs the outcome. When the builder is unavailable
        it logs the skip and returns ``None`` so the caller can no-op; otherwise
        it returns the upper-cased route (defaulting to ``OTHER``).

        Args:
            project_id: Project being queried.
            message: Current user message.
            summary: Builder input summary of prior turns.
            preview: Truncated message preview used in debug logs.
            msg_id: Per-message correlation id for logging.

        Returns:
            The classified route (e.g. ``DIRECT``, ``OTHER``), or ``None`` when
            the builder is unavailable.
        """
        b = build_query(project_id, summary, message)
        if b is None:
            try:
                logger.debug(
                    "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                    project_id,
                    msg_id,
                    "OTHER",
                    "false",
                    0.00,
                    0,
                    preview,
                )
                logger.debug(
                    "[ROUTE] project_id=%s message_id=%s route=%s namespaces=%s",
                    project_id,
                    msg_id,
                    "OTHER",
                    [],
                )
            except Exception:
                logger.debug("chat.builder debug logging failed project_id=%s", project_id, exc_info=True)
            logger.debug("builder unavailable; skipping RAG for this turn")
            return None

        route = (b.get("route") or "OTHER").upper()
        conf = float(b.get("confidence") or 0.0) if isinstance(b.get("confidence"), (int, float, str)) else 0.0
        topics = b.get("topics") or []
        standalone = b.get("standalone") or message

        try:
            builder_prev = (standalone or preview or "")[:self.settings.log_preview_max_chars]
            logger.debug(
                "[BUILDER] project_id=%s message_id=%s route=%s rag_used=%s confidence=%.2f topics_count=%s preview=\"%s\"",
                project_id,
                msg_id,
                route,
                "true",
                conf,
                len(topics or []),
                builder_prev,
            )
        except Exception as exc:
            logger.debug("chat.builder route logging failed project_id=%s detail=%s", project_id, exc)

        return route

    def _resolve_retrieval_policy(self, route: str) -> Tuple[RoutePolicy, int]:
        """Resolve the route policy and per-source retrieval depth for a route.

        Args:
            route: Classified route name.

        Returns:
            Tuple of ``(policy, per_source_k)`` where ``per_source_k`` is the
            per-source top-k derived from the base top-k and the route's
            retrieval multiplier.
        """
        pol = get_route_policy(route)
        per_source_k = compute_per_source_k(int(self.settings.base_top_k), float(pol.retrieval_multiplier))
        return pol, per_source_k

    def _write_rag_query_debug(
        self,
        *,
        project_id: str,
        route: str,
        pol: RoutePolicy,
        per_source_k: int,
        queries: list,
        message: str,
        primary_query: str,
        msg_id: str,
    ) -> None:
        """Write a best-effort RAG-query debug file for a turn.

        Records the route, retrieval parameters, user prompt, and assembled RAG
        query string. Failures are swallowed (debug-only; no-op unless debug
        files are enabled).

        Args:
            project_id: Project the turn belongs to.
            route: Classified route name.
            pol: Resolved route policy (source of multiplier/keep/score values).
            per_source_k: Per-source top-k used for retrieval.
            queries: Query strings issued for the turn (used for the count).
            message: Raw user message.
            primary_query: Contextualized RAG query string.
            msg_id: Per-message correlation id for logging.
        """
        try:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            fname = f"{ts}_rag_query.txt"
            body = (
                f"# timestamp: {ts}\n"
                f"# project_id: {project_id}\n"
                f"# route: {route}\n"
                f"# rag: true\n"
                f"# base_top_k: {int(self.settings.base_top_k)}\n"
                f"# retrieval_multiplier: {float(pol.retrieval_multiplier)}\n"
                f"# per_source_k: {int(per_source_k)}\n"
                f"# max_keep: {int(pol.max_keep)}\n"
                f"# min_score: {float(pol.min_score)}\n"
                f"# queries_count: {len([q for q in queries if q])}\n\n"
                "====== USER PROMPT ======\n"
                f"{message or ''}\n\n"
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

    def compute_rag_context(
        self,
        *,
        project_id: Optional[str],
        message: str,
        preview: str,
        msg_id: str,
        conversation_history: Optional[list[dict]],
    ) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
        """Build the RAG context prompt for a turn and report retrieval metrics.

        Classifies the route (see ``_classify_route``), applies the route policy
        (retrieval multiplier, keep limits, score threshold), retrieves and
        merges daily and main memory, and assembles the injected context text.
        No-ops when RAG-on-chat is disabled, no project is given, or the
        builder/route yields nothing to retrieve. Writes a best-effort RAG
        query debug file and sets the active route/namespace for logging.

        Args:
            project_id: Project to retrieve context for.
            message: Current user message.
            preview: Truncated message preview used in debug logs.
            msg_id: Per-message correlation id for logging.
            conversation_history: Prior turns used to summarize builder input.

        Returns:
            Tuple of ``(rag_system_prompt, primary_namespace, rag_metrics)``
            where ``rag_system_prompt`` is the injected context text (or
            ``None``), and ``rag_metrics`` reports route, counts, and token
            estimates for the turn.
        """
        rag_metrics = self._initial_rag_metrics()
        if (not self.settings.rag_on_chat) or (not project_id):
            return None, None, rag_metrics

        summary = self._build_builder_summary(project_id, conversation_history)
        route = self._classify_route(
            project_id=project_id,
            message=message,
            summary=summary,
            preview=preview,
            msg_id=msg_id,
        )
        if route is None:
            return None, None, rag_metrics

        set_route(route)
        primary_ns = route.lower()
        set_namespace(primary_ns)
        rag_metrics["route"] = route

        pol, per_source_k = self._resolve_retrieval_policy(route)
        if per_source_k <= 0:
            logger.info("Chat: skipping RAG due to route=%s per_source_k=%s", route, per_source_k)
            return None, primary_ns, rag_metrics

        daily_enabled = self._daily_enabled(project_id)
        primary_query = format_contextual_turn(message, summary)
        queries = [primary_query] if primary_query else []
        self._write_rag_query_debug(
            project_id=project_id,
            route=route,
            pol=pol,
            per_source_k=per_source_k,
            queries=queries,
            message=message,
            primary_query=primary_query,
            msg_id=msg_id,
        )

        rc = merge_daily_and_main(
            project_id=project_id,
            query=primary_query,
            daily_enabled=bool(daily_enabled),
            max_keep=int(pol.max_keep),
            route=route,
            per_source_k_override=int(per_source_k),
        )

        rag_system_prompt = rc["context_text"] if rc.get("context_text") else None
        rag_metrics.update(
            {
                "route": route,
                "rag_enabled": True,
                "retrieved_count": int(rc.get("ordered_candidates", 0) or 0),
                "kept_count": int(rc.get("selected_candidates", 0) or 0),
                "expanded_unique_chunks_after_merge": int(rc.get("expanded_unique_chunks_after_merge", 0) or 0),
                "rag_tokens_injected_est": int(rc.get("tokens_used", 0) or 0),
            }
        )
        return rag_system_prompt, primary_ns, rag_metrics

    def apply_rag_guidance(self, base_system_prompt: Optional[str], rag_system_prompt: Optional[str]) -> Optional[str]:
        """Append RAG usage guidance to the base system prompt when RAG context is present.

        Args:
            base_system_prompt: Base system prompt to augment; may be ``None``.
            rag_system_prompt: Injected RAG context; when falsy, no guidance is
                appended.

        Returns:
            The base prompt with RAG guidance appended, the guidance alone when
            there is no base prompt, or the base prompt unchanged when there is
            no RAG context.
        """
        if not rag_system_prompt:
            return base_system_prompt
        try:
            if base_system_prompt:
                return base_system_prompt.rstrip() + "\n\n" + RAG_SYSTEM_PROMPT.strip() + "\n"
            return RAG_SYSTEM_PROMPT.strip() + "\n"
        except (AttributeError, TypeError) as exc:
            logger.warning("chat.pipeline apply_rag_guidance failed detail=%s", exc)
            return base_system_prompt

    def enforce_model_whitelist(self, requested_model: Optional[str]) -> None:
        """Validate a requested model against the configured whitelist.

        Args:
            requested_model: Model id from the request; ``None`` uses the
                default and is always allowed.

        Raises:
            HTTPException: 400 when the requested model is not in
                ``settings.available_models``.
        """
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
        """Assemble the ordered chat message list sent to the LLM.

        Orders system prompt, assistant hint, RAG context, prior conversation
        turns, and the current user message, then records prompt-assembly
        token estimates to instrumentation.

        Args:
            base_system_prompt: Base system prompt; included as a system
                message when present.
            assistant_hint: Personality/preferences hint; included as an
                assistant message when present.
            rag_system_prompt: Injected RAG context; included as a system
                message when present.
            conversation_history: Prior turns appended as user/assistant
                messages.
            user_message: Current user message appended last.

        Returns:
            The list of role/content message dicts for the provider call.
        """
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
                    "prompt_system_tokens_est": int(estimate_tokens(base_system_prompt or "")),
                    "prompt_history_tokens_est": int(
                        estimate_tokens("\n".join(str((m.get("content") or "")) for m in (conversation_history or [])))
                    ),
                    "prompt_rag_tokens_est": int(estimate_tokens(rag_system_prompt or "")),
                    "prompt_profile_tokens_est": int(estimate_tokens(assistant_hint or "")),
                    "prompt_other_tokens_est": int(estimate_tokens(user_message or "")),
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
        """Append the user message to project working memory (no-op without a project).

        Args:
            project_id: Project to persist into; ``None`` is a no-op.
            message: User message text to append.
        """
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
        """Append the assistant message to project working memory with tagging metadata.

        Args:
            project_id: Project to persist into; ``None`` is a no-op.
            message: Assistant response text.
            namespace: Routing namespace for the message (defaults to
                ``"other"``).
            user_text_for_tagging: User text passed to the tagger for context.
            previous_pair_text_for_tagging: Prior pair text passed to the
                tagger for context.
            forget: When true, mark the pair as forgotten (e.g. chit-chat).
            skip_tagger: When true, skip tag generation for this message.
        """
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
