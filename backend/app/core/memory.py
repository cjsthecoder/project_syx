"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Memory management for Syx AGI Chatbot Framework.

Implements per-project working memory deques mirrored to DB `ChatMessage`.
System (RAG) messages are not stored. Provides last_context_tokens per project for stats.
"""

import logging
import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Deque, Tuple
from datetime import datetime, timedelta, timezone
from collections import deque

from filelock import FileLock
from sqlmodel import select
from .database import get_session
from .db_models import ChatMessage, Project
from .config import get_response_pruning_stage_config, get_settings
from ..pruning.light_response_pruner import Pruner, PrunerConfig, PruneResult
from ..rag.daily_store import append_pair
from ..utils.logging import get_namespace
from ..utils.tokens import count_tokens
from ..utils.debug_utils import write_debug_file
from ..tagging.tagger import tag_pair

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRUNER_CACHE_KEY: Optional[tuple[Any, ...]] = None
_PRUNER_CACHE: Optional[Pruner] = None


def _resolve_response_pruning_rules_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "backend/app/config/rules.json"))
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    return _REPO_ROOT / path


def _get_response_pruner(settings: Any) -> Pruner:
    global _PRUNER_CACHE
    global _PRUNER_CACHE_KEY

    rules_path = _resolve_response_pruning_rules_path(
        getattr(settings, "response_pruning_rules_path", "backend/app/config/rules.json")
    )
    stage_config = get_response_pruning_stage_config()
    cache_key = (
        str(rules_path),
        int(getattr(settings, "model_max_tokens", 128_000)),
        int(getattr(settings, "response_pruning_max_front_units", 3)),
        int(getattr(settings, "response_pruning_similarity_threshold", 90)),
        str(getattr(settings, "response_pruning_whitespace_mode", "compact_prose")),
        tuple(sorted(stage_config.items())),
    )

    if _PRUNER_CACHE is not None and _PRUNER_CACHE_KEY == cache_key:
        return _PRUNER_CACHE

    config = PrunerConfig(
        max_response_size=cache_key[1],
        max_front_units=cache_key[2],
        similarity_threshold=cache_key[3],
        whitespace_mode=cache_key[4],
        response_pruning=stage_config,
    )
    _PRUNER_CACHE = Pruner.from_file(rules_path, config=config, strip_comment_keys=True)
    _PRUNER_CACHE_KEY = cache_key
    return _PRUNER_CACHE


def _write_light_pruner_debug(
    *,
    project_id: str,
    original_response: str,
    pruned_response: str,
    result: Optional[PruneResult],
    error: Optional[Exception] = None,
) -> None:
    try:
        start_tokens = count_tokens(original_response)
        finished_tokens = count_tokens(pruned_response)
        tokens_saved = start_tokens - finished_tokens
        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        fname = f"{ts}_light_pruner.txt"
        body = (
            f"# timestamp: {ts}\n"
            f"# project_id: {project_id}\n"
            f"# success: {str(error is None).lower()}\n"
            f"# start_tokens: {start_tokens}\n"
            f"# finished_tokens: {finished_tokens}\n"
            f"# tokens_saved: {tokens_saved}\n"
        )
        if result is not None:
            body += (
                f"# changed: {str(bool(result.changed)).lower()}\n"
                f"# trimmed_side: {result.trimmed_side}\n"
                f"# front_units_removed: {result.front_units_removed}\n"
                f"# end_span_removed: {result.end_span_removed}\n"
                f"# blocked_by_safety: {str(bool(result.blocked_by_safety)).lower()}\n"
            )
        if error is not None:
            body += f"# error: {str(error)}\n"
        body += (
            "\n"
            "====== LIGHT PRUNER ORIGINAL RESPONSE ======\n"
            + (original_response or "")
            + "\n\n====== LIGHT PRUNER PRUNED RESPONSE ======\n"
            + (pruned_response or "")
            + "\n"
        )
        write_debug_file(project_id, f"prompts/{fname}", body)
    except Exception as exc:
        logger.warning(
            "[LIGHT_PRUNER] Failed writing debug dump project_id=%s detail=%s",
            project_id,
            exc,
        )


def _prune_assistant_for_tagger(
    *,
    project_id: str,
    assistant_text: str,
    settings: Any,
) -> str:
    original = str(assistant_text or "")
    try:
        if not bool(getattr(settings, "response_pruning_enabled", True)):
            start_tokens = count_tokens(original)
            logger.debug(
                "[LIGHT_PRUNER] project_id=%s enabled=false start_tokens=%s finished_tokens=%s tokens_saved=%s",
                project_id,
                start_tokens,
                start_tokens,
                0,
            )
            _write_light_pruner_debug(
                project_id=project_id,
                original_response=original,
                pruned_response=original,
                result=None,
            )
            return original

        result = _get_response_pruner(settings).prune(original)
        start_tokens = count_tokens(original)
        finished_tokens = count_tokens(result.pruned_text)
        logger.debug(
            "[LIGHT_PRUNER] project_id=%s changed=%s trimmed_side=%s start_tokens=%s finished_tokens=%s tokens_saved=%s",
            project_id,
            bool(result.changed),
            result.trimmed_side,
            start_tokens,
            finished_tokens,
            start_tokens - finished_tokens,
        )
        _write_light_pruner_debug(
            project_id=project_id,
            original_response=original,
            pruned_response=result.pruned_text,
            result=result,
        )
        return result.pruned_text
    except Exception as exc:
        start_tokens = count_tokens(original)
        logger.warning(
            "[LIGHT_PRUNER] Failed pruning assistant response; project_id=%s detail=%s",
            project_id,
            exc,
        )
        logger.debug(
            "[LIGHT_PRUNER] project_id=%s success=false start_tokens=%s finished_tokens=%s tokens_saved=%s",
            project_id,
            start_tokens,
            start_tokens,
            0,
        )
        _write_light_pruner_debug(
            project_id=project_id,
            original_response=original,
            pruned_response=original,
            result=None,
            error=exc,
        )
        return original


class MemoryManager:
    """Per-project working memory mirrored with DB for persistence."""

    def __init__(self):
        self.project_deques: Dict[str, Deque[Dict[str, Any]]] = {}
        self.last_context_tokens_per_project: Dict[str, int] = {}
        s = get_settings()
        self.limit = s.chat_history_limit
        self.pair_limit = s.chat_history_limit_pairs
        logger.info("Memory manager initialized (persistent mode)")

    @staticmethod
    def _normalize_question_candidates(value: Any) -> List[Dict[str, str]]:
        allowed = {"ignore", "answer_local", "answer_remote"}
        out: List[Dict[str, str]] = []
        if not isinstance(value, list):
            return out
        for item in value:
            if not isinstance(item, dict):
                continue
            q_text = str(item.get("question", "") or "").strip()
            q_topic = str(item.get("topic", "") or "").strip()
            q_resolution = str(item.get("resolution", "") or "").strip().lower()
            if not q_text:
                continue
            if q_resolution not in allowed:
                q_resolution = "ignore"
            out.append({"question": q_text, "topic": q_topic, "resolution": q_resolution})
        return out

    def _append_open_questions_artifact(
        self,
        *,
        project_id: str,
        assistant_message_id: Optional[int],
        user_message_id: Optional[int],
        namespace: str,
        semantic_handle: Optional[str],
        questions: List[Dict[str, str]],
    ) -> None:
        if not questions:
            return
        try:
            base_dir = os.path.join(get_settings().memory_root, project_id)
            os.makedirs(base_dir, exist_ok=True)
            artifact_path = os.path.join(base_dir, "open_questions.jsonl")
            state_dir = os.path.join(base_dir, "state")
            os.makedirs(state_dir, exist_ok=True)
            lock_path = os.path.join(state_dir, "open_questions.lock")
            legacy_lock_path = os.path.join(base_dir, "open_questions.lock")
            if os.path.isfile(legacy_lock_path) and not os.path.exists(lock_path):
                try:
                    os.replace(legacy_lock_path, lock_path)
                except OSError as exc:
                    logger.warning(
                        "memory questions lock migration failed project_id=%s detail=%s",
                        project_id,
                        exc,
                    )
            pair_id: Optional[str] = None
            if isinstance(user_message_id, int) and isinstance(assistant_message_id, int):
                pair_id = f"{user_message_id}:{assistant_message_id}"
            with FileLock(lock_path):
                with open(artifact_path, "a", encoding="utf-8", newline="\n") as f:
                    for idx, q in enumerate(questions, start=1):
                        payload: Dict[str, Any] = {
                            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "source": "tagger_ingest",
                            "project_id": project_id,
                            "assistant_message_id": assistant_message_id,
                            "user_message_id": user_message_id,
                            "pair_id": pair_id,
                            "namespace": (namespace or "other"),
                            "semantic_handle": (semantic_handle or ""),
                            "question_index": int(idx),
                            "question": q.get("question", ""),
                            "topic": q.get("topic", ""),
                            "resolution": q.get("resolution", "ignore"),
                        }
                        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[QUESTIONS][ARTIFACT] Failed writing open_questions.jsonl project=%s: %s", project_id, e)
    
    def _ensure_loaded(self, project_id: str) -> None:
        if project_id in self.project_deques:
            return
        # Use a deque sized to avoid dropping messages before pair-based pruning runs.
        # Ensure capacity for at least 2*pair_limit messages.
        maxlen = max(self.pair_limit * 2, self.limit)
        dq: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        try:
            with get_session() as session:
                rows = session.exec(
                    select(ChatMessage)
                    .where(ChatMessage.project_id == project_id)
                    .order_by(ChatMessage.created_at.desc())
                ).all()
                rows = rows[: maxlen]
                for r in reversed(rows):
                    dq.append({
                        "id": r.id,
                        "role": r.role,
                        "content": r.content,
                        "created_at": r.created_at,
                        "forget": getattr(r, 'forget', False),
                        "namespace": getattr(r, 'namespace', None),
                        "keep": getattr(r, 'keep', False),
                        "tags_meta_json": getattr(r, "tags_meta_json", None),
                        "semantic_handle": getattr(r, "semantic_handle", None),
                    })
        except Exception as e:
            logger.error(f"Failed to load history for {project_id}: {e}")
        # Cleanup unpaired trailing user and orphan leading assistant per current spec.
        self._cleanup_unpaired_edges(project_id, dq)
        self.project_deques[project_id] = dq

    def get_project_history(self, project_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        self._ensure_loaded(project_id)
        data = list(self.project_deques.get(project_id, deque()))
        return data if limit is None else data[-limit:]

    def append_user_message(self, project_id: str, content: str) -> None:
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            msg = ChatMessage(project_id=project_id, role="user", content=content, created_at=now)
            session.add(msg)
            session.commit()
            session.refresh(msg)
        self.project_deques[project_id].append({
            "id": msg.id,
            "role": "user",
            "content": content,
            "created_at": now,
        })
        self.prune_to_limit(project_id)

    def append_assistant_message(
        self,
        project_id: str,
        content: str,
        namespace: Optional[str] = None,
        *,
        user_text_for_tagging: Optional[str] = None,
        previous_pair_text_for_tagging: Optional[str] = None,
        forget: bool = False,
        skip_tagger: bool = False,
    ) -> None:
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.now(timezone.utc)
        ns = (namespace or get_namespace() or "other").lower()
        tags_meta: Optional[Dict[str, Any]] = None
        tags_meta_json: Optional[str] = None
        semantic_handle: Optional[str] = None
        question_candidates: List[Dict[str, str]] = []
        source_user_message_id: Optional[int] = None
        pruned_assistant_text: Optional[str] = None
        try:
            dq = self.project_deques.get(project_id)
            if dq:
                last = dq[-1]
                if isinstance(last, dict) and (last.get("role") == "user"):
                    uid = last.get("id")
                    source_user_message_id = int(uid) if isinstance(uid, int) else None
        except Exception as exc:
            logger.warning(
                "append_assistant_message source user lookup failed; project_id=%s detail=%s",
                project_id,
                exc,
            )
            source_user_message_id = None
        # Tag immediately after assistant reply using the immediately previous active pair as context anchor.
        try:
            if (not bool(skip_tagger)) and (user_text_for_tagging is not None):
                settings = get_settings()
                assistant_text_for_tagging = _prune_assistant_for_tagger(
                    project_id=project_id,
                    assistant_text=content,
                    settings=settings,
                )
                if assistant_text_for_tagging != str(content or ""):
                    pruned_assistant_text = assistant_text_for_tagging
                tagged = tag_pair(
                    user_text_for_tagging,
                    assistant_text_for_tagging,
                    previous_pair_text=previous_pair_text_for_tagging,
                    project_id=project_id,
                )
                if isinstance(tagged, dict):
                    tags_meta = {
                        "topics": tagged.get("topics", "") or "",
                        "intent": tagged.get("intent", "") or "",
                        "type": tagged.get("type", "") or "",
                        # semantic_handle is required but may be empty; store None only if missing.
                        "semantic_handle": tagged.get("semantic_handle", None),
                    }
                    if pruned_assistant_text is not None:
                        # Private rolloff-only field: daily/LTM should carry pruned assistant text.
                        tags_meta["_pruned_assistant_text"] = pruned_assistant_text
                    question_candidates = self._normalize_question_candidates(tagged.get("questions"))
                    semantic_handle = tags_meta.get("semantic_handle", None)  # type: ignore[assignment]
                    try:
                        tags_meta_json = json.dumps(tags_meta, ensure_ascii=False)
                    except Exception as exc:
                        logger.warning(
                            "append_assistant_message tag metadata serialization failed; project_id=%s detail=%s",
                            project_id,
                            exc,
                        )
                        tags_meta_json = None
        except Exception as exc:
            logger.warning(
                "append_assistant_message tagging failed; project_id=%s detail=%s",
                project_id,
                exc,
            )
            tags_meta = None
            tags_meta_json = None
            semantic_handle = None
        with get_session() as session:
            msg = ChatMessage(
                project_id=project_id,
                role="assistant",
                content=content,
                created_at=now,
                forget=bool(forget),
                namespace=ns,
                keep=False,
                tags_meta_json=tags_meta_json,
                semantic_handle=semantic_handle,
            )
            session.add(msg)
            # Persist last non-empty semantic handle across sleep flush (ChatMessage is wiped).
            try:
                if isinstance(semantic_handle, str) and semantic_handle.strip():
                    p = session.get(Project, project_id)
                    if p is not None:
                        p.last_semantic_handle = semantic_handle.strip()
                        session.add(p)
            except Exception as exc:
                logger.warning(
                    "append_assistant_message failed updating project semantic handle; project_id=%s detail=%s",
                    project_id,
                    exc,
                )
            session.commit()
            session.refresh(msg)
        self.project_deques[project_id].append({
            "id": msg.id,
            "role": "assistant",
            "content": content,
            "created_at": now,
            "forget": bool(forget),
            "namespace": ns,
            "keep": False,
            "tags_meta_json": tags_meta_json,
            "semantic_handle": semantic_handle,
            "pruned_content": pruned_assistant_text,
        })
        self._append_open_questions_artifact(
            project_id=project_id,
            assistant_message_id=(int(msg.id) if isinstance(msg.id, int) else None),
            user_message_id=source_user_message_id,
            namespace=ns,
            semantic_handle=semantic_handle if isinstance(semantic_handle, str) else None,
            questions=question_candidates,
        )
        self.prune_to_limit(project_id)

    def prune_to_limit(self, project_id: str) -> None:
        self._ensure_loaded(project_id)
        dq = self.project_deques[project_id]
        # If we have at least one complete pair at the head, and pair_limit exceeded, roll off the oldest pair
        while self._pair_count(dq) > self.pair_limit:
            self._rolloff_oldest_pair(project_id, dq)

    def _pair_count(self, dq: Deque[Dict[str, Any]]) -> int:
        count = 0
        i = 0
        n = len(dq)
        while i + 1 < n:
            if dq[i].get("role") == "user" and dq[i+1].get("role") == "assistant":
                count += 1
                i += 2
            else:
                i += 1
        return count

    def _rolloff_oldest_pair(self, project_id: str, dq: Deque[Dict[str, Any]]) -> None:
        # Ensure the first two form a pair; if not, clean or skip until a pair is found
        while len(dq) >= 2:
            first, second = dq[0], dq[1]
            if first.get("role") == "user" and second.get("role") == "assistant":
                break
            # Delete stray message from DB and drop it
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[0].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting stray message {dq[0].get('id')}: {e}")
            dq.popleft()
        if len(dq) < 2:
            return
        user_msg = dq.popleft()
        asst_msg = dq.popleft()
        user_text = user_msg.get('content') or ''
        # Append to daily if enabled and not forgotten; on any error we still drop per spec
        try:
            if bool(asst_msg.get("forget")):
                logger.info("[FORGET] Skipped pair (forget flag set) user_id=%s assistant_id=%s", str(user_msg.get("id")), str(asst_msg.get("id")))
            elif self._is_daily_enabled(project_id):
                ns = (asst_msg.get("namespace") or get_namespace() or "other").lower()
                keep = bool(asst_msg.get("keep"))
                # Roll-off does NOT call the tagger. It reuses metadata stored on the assistant row.
                tags_meta = None
                tags_meta_json = asst_msg.get("tags_meta_json")
                if isinstance(tags_meta_json, str) and tags_meta_json.strip():
                    try:
                        parsed = json.loads(tags_meta_json)
                        if isinstance(parsed, dict):
                            tags_meta = parsed
                    except Exception:
                        tags_meta = None
                pruned_from_meta = None
                if isinstance(tags_meta, dict):
                    pruned_candidate = tags_meta.get("_pruned_assistant_text")
                    if isinstance(pruned_candidate, str) and pruned_candidate.strip():
                        pruned_from_meta = pruned_candidate
                pruned_from_deque = asst_msg.get("pruned_content")
                asst_text = (
                    pruned_from_deque
                    if isinstance(pruned_from_deque, str) and pruned_from_deque.strip()
                    else pruned_from_meta
                    if isinstance(pruned_from_meta, str) and pruned_from_meta.strip()
                    else asst_msg.get("content") or ""
                )
                pair_text = f"User: {user_text}\nAssistant: {asst_text}"
                tokens = int(count_tokens(pair_text))
                limit = get_settings().log_preview_max_chars
                rp = (asst_text or "")[:limit]
                logger.debug(
                    "[ROLLOFF] project_id=%s user_id=%s assistant_id=%s tokens_approx=%s pruned_for_daily=%s response_preview=\"%s\"",
                    project_id,
                    str(user_msg.get("id")),
                    str(asst_msg.get("id")),
                    str(tokens),
                    str(asst_text != (asst_msg.get("content") or "")).lower(),
                    rp,
                )
                tags_block = ""
                if isinstance(tags_meta, dict):
                    try:
                        topics = str(tags_meta.get("topics", "") or "")
                        intent = str(tags_meta.get("intent", "") or "")
                        tag_type = str(tags_meta.get("type", "") or "")
                        semantic_handle = tags_meta.get("semantic_handle", None)
                        lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
                        if semantic_handle is not None:
                            lines.append(f"#semantic_handle: {str(semantic_handle) if semantic_handle is not None else ''}")
                        tags_block = "\n".join(lines) + "\n"
                    except Exception:
                        tags_block = ""
                embed_text = (tags_block + pair_text) if tags_block else pair_text
                ok = append_pair(
                    project_id,
                    pair_text,
                    int(user_msg.get("id")),
                    int(asst_msg.get("id")),
                    int(tokens),
                    namespace=ns,
                    keep=keep,
                    embed_override=embed_text,
                    tags_meta={
                        key: value
                        for key, value in dict(tags_meta or {}).items()
                        if not str(key).startswith("_")
                    },
                )
            else:
                logger.info("[DailyRAG] Skipping daily append (disabled for project=%s)", project_id)
        except Exception as e:
            logger.error(f"DailyRAG rolloff append failed: {e}")
        # Delete both rows from DB
        try:
            with get_session() as session:
                for mid in (user_msg.get("id"), asst_msg.get("id")):
                    row = session.get(ChatMessage, mid)
                    if row:
                        session.delete(row)
                session.commit()
        except Exception as e:
            logger.error(f"Failed deleting rolled-off DB rows: {e}")

    def _cleanup_unpaired_edges(self, project_id: str, dq: Deque[Dict[str, Any]]) -> None:
        """Delete orphan leading assistant messages and trailing unpaired user messages from DB and deque."""
        # Clean orphan assistants at the head
        while len(dq) and dq[0].get("role") != "user":
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[0].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting orphan assistant {dq[0].get('id')}: {e}")
            dq.popleft()
        # Clean trailing unpaired user at the tail
        while len(dq) and dq[-1].get("role") != "assistant":
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[-1].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting trailing unpaired message {dq[-1].get('id')}: {e}")
            dq.pop()

    def _is_daily_enabled(self, project_id: str) -> bool:
        try:
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is None:
                    return True
                return bool(p.daily_rag_enabled)
        except Exception as e:
            logger.warning("Failed to read project daily flag for %s: %s; defaulting to True", project_id, e)
            return True

    def get_active_pair_count(self, project_id: str) -> int:
        self._ensure_loaded(project_id)
        dq = self.project_deques.get(project_id) or deque()
        return self._pair_count(dq)

    def set_last_context_tokens(self, project_id: str, tokens: int) -> None:
        self.last_context_tokens_per_project[project_id] = max(0, int(tokens))

    def get_last_context_tokens(self, project_id: str) -> int:
        return int(self.last_context_tokens_per_project.get(project_id, 0))
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        # Deprecated (project-scoped history is used instead).
        return []
    
    def search_memory(
        self, 
        query: str, 
        conversation_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search through stored memories (RAG functionality).
        
        Args:
            query: Search query
            conversation_id: Optional conversation to search within
            limit: Maximum number of results
            
        Returns:
            List of relevant memories
        """
        # TODO: Implement FAISS-based search.
        logger.info(f"Memory search requested: '{query}' (stub - not yet implemented)")
        
        return [{
            "content": f"Memory search for '{query}' not yet implemented",
            "relevance_score": 0.0,
            "source": "stub",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    
    def cleanup_old_memories(
        self, 
        retention_days: int = 30,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clean up old memories (memory pruning).
        
        Args:
            retention_days: Number of days to retain memories
            conversation_id: Optional specific conversation to clean
            
        Returns:
            Cleanup statistics
        """
        # TODO: Implement memory pruning.
        logger.info("Memory cleanup requested (stub - not yet implemented)")
        
        return {
            "items_cleaned": 0,
            "memory_usage_before": "0MB",
            "memory_usage_after": "0MB",
            "retention_days": retention_days,
            "status": "stub_mode"
        }
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics."""
        total_projects = len(self.project_deques)
        total_messages = sum(len(dq) for dq in self.project_deques.values())
        return {
            "total_conversations": total_projects,
            "total_messages": total_messages,
            "memory_mode": "persistent",
            "features_available": {
                "rag_search": False,
                "memory_pruning": False,
                "conversation_storage": True
            }
        }


# Global instances
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


# Convenience functions

def store_conversation(
    conversation_id: str, 
    message: str, 
    response: str, 
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Store a conversation message."""
    manager = get_memory_manager()
    return manager.store_message(conversation_id, message, response, metadata)


def set_last_context_tokens(project_id: str, tokens: int) -> None:
    manager = get_memory_manager()
    manager.set_last_context_tokens(project_id, tokens)


def get_last_context_tokens(project_id: str) -> int:
    manager = get_memory_manager()
    return manager.get_last_context_tokens(project_id)


def search_conversation_memory(
    query: str, 
    conversation_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search conversation memory."""
    manager = get_memory_manager()
    return manager.search_memory(query, conversation_id)


