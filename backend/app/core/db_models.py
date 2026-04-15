"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True, index=True)
    name: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    system: bool = Field(default=False, description="System project (non-deletable/non-renamable)")
    daily_rag_enabled: bool = Field(default=True, description="V2.3: Keep Daily History per project")
    # Persist a minimal "recent summary" seed across sleep flush (ChatMessage is wiped).
    last_semantic_handle: Optional[str] = Field(
        default=None,
        description="V3.x: last non-empty semantic_handle observed for the project; used as builder fallback when active history is empty",
    )


class File(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    embedding_status: str = Field(default="indexed", description="pending|indexed|failed")
    page_count: int = Field(default=1, description="Pages for PDFs; 1 for text files")
    token_count: int = Field(default=0, description="Tokens computed for this file")



class ChatMessage(SQLModel, table=True):
    """Persistent chat messages per project (V2.2)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    role: str = Field(description="user|assistant")
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    forget: bool = Field(default=False, description="V2.7: if true, skip roll-off embedding and daily.txt")
    namespace: Optional[str] = Field(default=None, description="V2.7: primary namespace captured at assistant creation")
    keep: bool = Field(default=False, description="V2.7.7: user preference tag propagated into daily headers/metadata")
    # Store per-assistant metadata produced immediately after response.
    # tags_meta_json stores parsed tagger output (topics/intent/type/semantic_handle).
    tags_meta_json: Optional[str] = Field(default=None, description="JSON string for tagger metadata; nullable on failure")
    semantic_handle: Optional[str] = Field(default=None, description="Short noun phrase naming the exchange; nullable on failure")

