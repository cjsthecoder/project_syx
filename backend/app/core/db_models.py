"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
SQLModel database models for the Syx persistence layer.

This module defines the Project, File, and ChatMessage tables and a shared UTC
timestamp helper used as the default for created/updated fields.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current moment with UTC tzinfo attached, used as the default for
        created/updated timestamp columns.
    """
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    """A workspace that owns files, chat history, and per-project memory.

    Persisted ``project`` table and the top of the ownership hierarchy: ``File``
    and ``ChatMessage`` rows reference a project by id. Beyond identity it
    stores per-project flags (system/non-deletable, Daily RAG toggle) and a
    ``last_semantic_handle`` seed that survives the sleep flush that wipes
    ``ChatMessage`` rows, so the builder has a fallback when active history is
    empty.
    """

    id: str = Field(primary_key=True, index=True)
    name: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    system: bool = Field(default=False, description="System project (non-deletable/non-renamable)")
    daily_rag_enabled: bool = Field(default=True, description="Keep Daily History per project")
    # Persist a minimal "recent summary" seed across sleep flush (ChatMessage is wiped).
    last_semantic_handle: Optional[str] = Field(
        default=None,
        description="Last non-empty semantic_handle observed for the project; used as builder fallback when active history is empty",
    )


class File(SQLModel, table=True):
    """An uploaded source document tracked for embedding/indexing.

    Persisted ``file`` table scoped to a project. Stores upload metadata
    (filename, size, content type) plus indexing bookkeeping (embedding status,
    page and token counts) updated by the RAG rebuild pipeline.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    embedding_status: str = Field(default="indexed", description="pending|indexed|failed")
    page_count: int = Field(default=1, description="Pages for PDFs; 1 for text files")
    token_count: int = Field(default=0, description="Tokens computed for this file")



class ChatMessage(SQLModel, table=True):
    """A persisted chat message (user or assistant turn) within a project.

    Persisted ``chatmessage`` table backing the active conversation window.
    Assistant rows additionally carry post-response tagger output
    (``tags_meta_json``, ``semantic_handle``, ``namespace``) and the
    ``forget``/``keep`` flags that steer roll-off embedding and daily.md
    headers. Rows are consumed and removed during the sleep flush once their
    pair is persisted to Daily memory.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    role: str = Field(description="user|assistant")
    content: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
    forget: bool = Field(default=False, description="If true, skip roll-off embedding and daily.md")
    namespace: Optional[str] = Field(default=None, description="Primary namespace captured at assistant creation")
    keep: bool = Field(default=False, description="User preference tag propagated into daily headers/metadata")
    # Store per-assistant metadata produced immediately after response.
    # tags_meta_json stores parsed tagger output (topics/intent/type/semantic_handle).
    tags_meta_json: Optional[str] = Field(default=None, description="JSON string for tagger metadata; nullable on failure")
    semantic_handle: Optional[str] = Field(default=None, description="Short noun phrase naming the exchange; nullable on failure")

