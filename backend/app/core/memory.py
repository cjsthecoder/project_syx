"""
Memory management for Morpheus AGI Chatbot Framework.

V2.2: Implements per-project working memory deques mirrored to DB `ChatMessage`.
System (RAG) messages are not stored. Provides last_context_tokens per project for stats.
"""

import logging
from typing import Optional, List, Dict, Any, Deque
from datetime import datetime, timedelta
from collections import deque

from sqlmodel import select
from .database import get_session
from .db_models import ChatMessage
from .config import get_settings

logger = logging.getLogger(__name__)


class MemoryManager:
    """Per-project working memory mirrored with DB for persistence."""

    def __init__(self):
        self.project_deques: Dict[str, Deque[Dict[str, Any]]] = {}
        self.last_context_tokens_per_project: Dict[str, int] = {}
        self.limit = get_settings().chat_history_limit
        logger.info("Memory manager initialized (v2.2 persistent mode)")
    
    def _ensure_loaded(self, project_id: str) -> None:
        if project_id in self.project_deques:
            return
        dq: Deque[Dict[str, Any]] = deque(maxlen=self.limit)
        try:
            with get_session() as session:
                rows = session.exec(
                    select(ChatMessage)
                    .where(ChatMessage.project_id == project_id)
                    .order_by(ChatMessage.created_at.desc())
                ).all()
                rows = rows[: self.limit]
                for r in reversed(rows):
                    dq.append({
                        "id": r.id,
                        "role": r.role,
                        "content": r.content,
                        "created_at": r.created_at,
                    })
        except Exception as e:
            logger.error(f"Failed to load history for {project_id}: {e}")
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

    def append_assistant_message(self, project_id: str, content: str) -> None:
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.utcnow()
        with get_session() as session:
            msg = ChatMessage(project_id=project_id, role="assistant", content=content, created_at=now)
            session.add(msg)
            session.commit()
            session.refresh(msg)
        self.project_deques[project_id].append({
            "id": msg.id,
            "role": "assistant",
            "content": content,
            "created_at": now,
        })
        self.prune_to_limit(project_id)

    def prune_to_limit(self, project_id: str) -> None:
        self._ensure_loaded(project_id)
        dq = self.project_deques[project_id]
        while len(dq) > self.limit:
            oldest = dq.popleft()
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, oldest.get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed pruning message {oldest.get('id')}: {e}")

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
        total_conversations = len(self.conversations)
        total_messages = sum(len(conv) for conv in self.conversations.values())
        
        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "memory_mode": "stub",
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
