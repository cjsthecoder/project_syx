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
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
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
    """Persistent chat messages per project."""
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

