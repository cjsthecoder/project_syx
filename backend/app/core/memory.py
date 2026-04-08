"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Memory management for Morpheus AGI Chatbot Framework.

V2.2: Implements per-project working memory deques mirrored to DB `ChatMessage`.
System (RAG) messages are not stored. Provides last_context_tokens per project for stats.
"""

import logging
import os
import json
from typing import Optional, List, Dict, Any, Deque, Tuple
from datetime import datetime, timedelta
from collections import deque

from filelock import FileLock
from sqlmodel import select
from .database import get_session
from .db_models import ChatMessage, Project
from .config import get_settings
from .daily_rag import append_pair
from ..utils.logging import get_message_id, get_namespace
from .tagger import tag_pair

logger = logging.getLogger(__name__)


class MemoryManager:
    """Per-project working memory mirrored with DB for persistence."""

    def __init__(self):
        self.project_deques: Dict[str, Deque[Dict[str, Any]]] = {}
        self.last_context_tokens_per_project: Dict[str, int] = {}
        s = get_settings()
        self.limit = s.chat_history_limit
        self.pair_limit = s.chat_history_limit_pairs
        logger.info("Memory manager initialized (v2.2 persistent mode)")

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
            base_dir = os.path.join("memory", project_id)
            os.makedirs(base_dir, exist_ok=True)
            artifact_path = os.path.join(base_dir, "open_questions.jsonl")
            lock_path = os.path.join(base_dir, "open_questions.lock")
            pair_id: Optional[str] = None
            if isinstance(user_message_id, int) and isinstance(assistant_message_id, int):
                pair_id = f"{user_message_id}:{assistant_message_id}"
            with FileLock(lock_path):
                with open(artifact_path, "a", encoding="utf-8", newline="\n") as f:
                    for idx, q in enumerate(questions, start=1):
                        payload: Dict[str, Any] = {
                            "ts": datetime.utcnow().isoformat() + "Z",
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
        # Cleanup unpaired trailing user and orphan leading assistant per V2.3 spec
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
        now = datetime.utcnow()
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
        now = datetime.utcnow()
        ns = (namespace or get_namespace() or "other").lower()
        tags_meta: Optional[Dict[str, Any]] = None
        tags_meta_json: Optional[str] = None
        semantic_handle: Optional[str] = None
        question_candidates: List[Dict[str, str]] = []
        source_user_message_id: Optional[int] = None
        try:
            dq = self.project_deques.get(project_id)
            if dq:
                last = dq[-1]
                if isinstance(last, dict) and (last.get("role") == "user"):
                    uid = last.get("id")
                    source_user_message_id = int(uid) if isinstance(uid, int) else None
        except Exception:
            source_user_message_id = None
        # V3.x: tag immediately after assistant reply using the immediately previous active pair as context anchor.
        try:
            if (not bool(skip_tagger)) and (user_text_for_tagging is not None):
                tagged = tag_pair(
                    user_text_for_tagging,
                    content,
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
                    question_candidates = self._normalize_question_candidates(tagged.get("questions"))
                    semantic_handle = tags_meta.get("semantic_handle", None)  # type: ignore[assignment]
                    try:
                        tags_meta_json = json.dumps(tags_meta, ensure_ascii=False)
                    except Exception:
                        tags_meta_json = None
        except Exception:
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
            # V3.x: persist last non-empty semantic handle across sleep flush (ChatMessage is wiped).
            try:
                if isinstance(semantic_handle, str) and semantic_handle.strip():
                    p = session.get(Project, project_id)
                    if p is not None:
                        p.last_semantic_handle = semantic_handle.strip()
                        session.add(p)
            except Exception:
                pass
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
        asst_text = asst_msg.get('content') or ''
        pair_text = f"User: {user_text}\nAssistant: {asst_text}"
        # approximate tokens
        try:
            import tiktoken  # type: ignore
            enc = tiktoken.get_encoding("cl100k_base")
            tokens = len(enc.encode(pair_text))
        except Exception as e:
            logger.debug("Token count fallback used due to error: %s", e)
            tokens = len((pair_text or "").split())
        mid = get_message_id() or "-"
        limit = get_settings().log_preview_max_chars
        pp = (user_msg.get('content') or '')[:limit]
        rp = (asst_msg.get('content') or '')[:limit]
        logger.debug(
            "[ROLLOFF] project_id=%s message_id=%s user_id=%s assistant_id=%s tokens_approx=%s prompt_preview=\"%s\" response_preview=\"%s\"",
            project_id,
            mid,
            str(user_msg.get("id")),
            str(asst_msg.get("id")),
            str(tokens),
            pp,
            rp,
        )
        # Append to daily if enabled and not forgotten; on any error we still drop per spec
        try:
            if bool(asst_msg.get("forget")):
                logger.info("[FORGET] Skipped pair (forget flag set) user_id=%s assistant_id=%s", str(user_msg.get("id")), str(asst_msg.get("id")))
            elif self._is_daily_enabled(project_id):
                ns = (asst_msg.get("namespace") or get_namespace() or "other").lower()
                keep = bool(asst_msg.get("keep"))
                # V3.x: roll-off does NOT call the tagger. It reuses metadata stored on the assistant row.
                tags_meta = None
                tags_meta_json = asst_msg.get("tags_meta_json")
                if isinstance(tags_meta_json, str) and tags_meta_json.strip():
                    try:
                        parsed = json.loads(tags_meta_json)
                        if isinstance(parsed, dict):
                            tags_meta = parsed
                    except Exception:
                        tags_meta = None
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
                    tags_meta=tags_meta,
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
        # Deprecated in V2.2 (project-scoped history is used instead)
        return []
    
    def search_memory(
        self, 
        query: str, 
        conversation_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search through stored memories (RAG functionality - V2).
        
        Args:
            query: Search query
            conversation_id: Optional conversation to search within
            limit: Maximum number of results
            
        Returns:
            List of relevant memories
        """
        # TODO: Implement FAISS-based search in Version 2
        logger.info(f"Memory search requested: '{query}' (stub - will be implemented in V2)")
        
        return [{
            "content": f"Memory search for '{query}' not yet implemented",
            "relevance_score": 0.0,
            "source": "stub",
            "timestamp": datetime.utcnow().isoformat()
        }]
    
    def cleanup_old_memories(
        self, 
        retention_days: int = 30,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clean up old memories (Memory Pruning - V3).
        
        Args:
            retention_days: Number of days to retain memories
            conversation_id: Optional specific conversation to clean
            
        Returns:
            Cleanup statistics
        """
        # TODO: Implement memory pruning in Version 3
        logger.info(f"Memory cleanup requested (stub - will be implemented in V3)")
        
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


class RAGProvider:
    """RAG (Retrieval-Augmented Generation) provider - V2."""
    
    def __init__(self):
        """Initialize the RAG provider."""
        logger.info("RAG provider initialized (stub mode)")
    
    def index_documents(
        self, 
        documents: List[str], 
        project_id: Optional[str] = None
    ) -> bool:
        """
        Index documents for RAG search.
        
        Args:
            documents: List of documents to index
            project_id: Project context
            
        Returns:
            True if indexed successfully
        """
        # TODO: Implement FAISS indexing in Version 2
        logger.info(f"Document indexing requested (stub - will be implemented in V2)")
        return True
    
    def search_documents(
        self, 
        query: str, 
        project_id: Optional[str] = None,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search indexed documents.
        
        Args:
            query: Search query
            project_id: Project context
            max_results: Maximum number of results
            
        Returns:
            List of relevant documents
        """
        # TODO: Implement FAISS search in Version 2
        logger.info(f"RAG search requested: '{query}' (stub - will be implemented in V2)")
        
        return [{
            "content": f"RAG search for '{query}' not yet implemented",
            "relevance_score": 0.0,
            "source": "stub",
            "project_id": project_id
        }]
    
    def get_rag_stats(self) -> Dict[str, Any]:
        """Get RAG system statistics."""
        return {
            "indexed_documents": 0,
            "rag_mode": "stub",
            "features_available": {
                "document_indexing": False,
                "semantic_search": False,
                "project_isolation": False
            }
        }


# Global instances
_memory_manager: Optional[MemoryManager] = None
_rag_provider: Optional[RAGProvider] = None


def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def get_rag_provider() -> RAGProvider:
    """Get the global RAG provider instance."""
    global _rag_provider
    if _rag_provider is None:
        _rag_provider = RAGProvider()
    return _rag_provider


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


def perform_rag_search(
    query: str, 
    project_id: Optional[str] = None,
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """Perform RAG search."""
    rag = get_rag_provider()
    return rag.search_documents(query, project_id, max_results)
