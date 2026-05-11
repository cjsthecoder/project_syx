"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""Pydantic models for agent memory search responses."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentMemorySnippet(BaseModel):
    snippet_number: int
    source: Optional[str] = None
    cos: Optional[float] = None
    score: Optional[float] = None
    file: Optional[str] = None
    page: Optional[Any] = None
    source_document_id: Optional[str] = None
    chunk_index_start: Optional[int] = None
    chunk_index_end: Optional[int] = None
    chunk_index_range: Optional[str] = None
    chunk_indexes: Optional[List[int]] = None
    memory_id: Optional[str] = None
    entry_type: Optional[str] = None
    source_agent: Optional[str] = None
    source_scope: Optional[str] = None
    current_scope: Optional[str] = None
    semantic_handle: Optional[str] = None
    topics: Optional[List[str]] = None
    artifact_path: Optional[str] = None
    result_mode: str = "unbounded_chunk_group"
    text: str = ""


class AgentMemorySearchResponse(BaseModel):
    project_name: str
    project_id: str
    category: str
    query: str
    model: Optional[str] = None
    snippet_count: int = 0
    bounded_result_count: int = 0
    unbounded_result_count: int = 0
    snippets: List[AgentMemorySnippet] = Field(default_factory=list)

    def to_response_dict(self) -> Dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        if self.model is None:
            data.pop("model", None)
        return data
