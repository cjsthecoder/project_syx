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
from typing import Optional, List, Dict, Any, Deque, Tuple
from datetime import datetime, timedelta
from collections import deque

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

    def append_assistant_message(self, project_id: str, content: str, namespace: Optional[str] = None) -> None:
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.utcnow()
        ns = (namespace or get_namespace() or "general").lower()
        with get_session() as session:
            msg = ChatMessage(project_id=project_id, role="assistant", content=content, created_at=now, namespace=ns, keep=False)
            session.add(msg)
            session.commit()
            session.refresh(msg)
        self.project_deques[project_id].append({
            "id": msg.id,
            "role": "assistant",
            "content": content,
            "created_at": now,
            "forget": False,
            "namespace": ns,
            "keep": False,
        })
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
                ns = (asst_msg.get("namespace") or get_namespace() or "general").lower()
                keep = bool(asst_msg.get("keep"))
                # V3.4: attempt to generate tag lines and embed them into FAISS text (daily.txt unchanged)
                tags_lines = None
                try:
                    tags_lines = tag_pair(user_text, asst_text, previous_pair_text=None)
                except Exception:
                    tags_lines = None
                embed_text = (("\n".join(tags_lines) + "\n" + pair_text) if tags_lines else pair_text)
                tags_meta = None
                if tags_lines:
                    try:
                        topics = tags_lines[0][8:].strip()
                        intent = tags_lines[1][8:].strip()
                        tag_type = tags_lines[2][6:].strip()
                        tags_meta = {"topics": topics, "intent": intent, "type": tag_type}
                    except Exception:
                        tags_meta = None
                append_pair(
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
