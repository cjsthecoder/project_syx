"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""Pydantic models for agent memory search responses."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentMemorySnippet(BaseModel):
    """One structured retrieval snippet returned by agent memory search.

    Represents a single result in the agent search response: its scoring,
    source-document provenance, chunk-range identity, memory metadata, and the
    bounded/unbounded entry-expansion status. Optional fields are omitted from
    the serialized response (see :meth:`AgentMemorySearchResponse.to_response_dict`).
    """

    snippet_number: int = Field(description="1-based position of this snippet in the result list")
    source: Optional[str] = Field(default=None, description="Retrieval source bucket (e.g. daily or main)")
    cos: Optional[float] = Field(default=None, description="Raw cosine inner-product score")
    score: Optional[float] = Field(default=None, description="Mapped similarity score in [0, 1]")
    file: Optional[str] = Field(default=None, description="Originating file name, when known")
    page: Optional[Any] = Field(default=None, description="Page locator for paged sources (e.g. PDFs)")
    source_document_id: Optional[str] = Field(default=None, description="Stable id of the source document")
    chunk_index_start: Optional[int] = Field(default=None, description="First chunk index in the snippet's range")
    chunk_index_end: Optional[int] = Field(default=None, description="Last chunk index in the snippet's range")
    chunk_index_range: Optional[str] = Field(default=None, description="Human-readable chunk range (e.g. '3-5')")
    chunk_indexes: Optional[List[int]] = Field(default=None, description="Explicit chunk indexes composing the snippet")
    memory_id: Optional[str] = Field(default=None, description="Stable Syx memory entry id, when applicable")
    entry_type: Optional[str] = Field(default=None, description="Memory entry type (e.g. dream, daily)")
    source_agent: Optional[str] = Field(default=None, description="Agent that authored the source entry")
    source_scope: Optional[str] = Field(default=None, description="Scope recorded on the source entry")
    current_scope: Optional[str] = Field(default=None, description="Scope active at retrieval time")
    semantic_handle: Optional[str] = Field(default=None, description="Short noun phrase naming the entry")
    topics: Optional[List[str]] = Field(default=None, description="Topic tags associated with the entry")
    artifact_path: Optional[str] = Field(default=None, description="Path to a backing artifact, when present")
    result_mode: str = Field(default="unbounded_chunk_group", description="Result shaping mode for this snippet")
    entry_expansion_status: Optional[str] = Field(default=None, description="Outcome of full-entry expansion")
    entry_expansion_method: Optional[str] = Field(default=None, description="Method used to expand the entry")
    entry_expansion_error: Optional[str] = Field(default=None, description="Error message when expansion failed")
    entry_expansion_warning: Optional[str] = Field(default=None, description="Non-fatal warning raised during expansion")
    entry_expansion_truncated: Optional[bool] = Field(default=None, description="Whether expanded text was truncated")
    entry_expansion_original_chars: Optional[int] = Field(default=None, description="Character count before truncation")
    entry_expansion_returned_chars: Optional[int] = Field(default=None, description="Character count actually returned")
    entry_expansion_max_chars: Optional[int] = Field(default=None, description="Truncation budget applied to expansion")
    entry_expansion_truncation_reason: Optional[str] = Field(default=None, description="Why the expanded text was truncated")
    text: str = Field(default="", description="Snippet body text returned to the agent")


class AgentMemorySearchResponse(BaseModel):
    """Top-level response body for the agent memory search endpoint.

    Echoes the resolved query context (project, category, query, model) and
    carries the ordered snippets plus counts. Serialize with
    :meth:`to_response_dict` to drop null fields and the unset ``model`` key.
    """

    project_name: str = Field(description="Human-readable name of the searched project")
    project_id: str = Field(description="Id of the searched project")
    category: str = Field(description="Memory category that was searched")
    query: str = Field(description="The query string that was executed")
    model: Optional[str] = Field(default=None, description="Embedding model used, when reported")
    snippet_count: int = Field(default=0, description="Total snippets returned")
    bounded_result_count: int = Field(default=0, description="Snippets returned as bounded chunk groups")
    unbounded_result_count: int = Field(default=0, description="Snippets returned as unbounded chunk groups")
    snippets: List[AgentMemorySnippet] = Field(default_factory=list, description="Ordered retrieval snippets")

    def to_response_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-ready dict, omitting null fields and unset model.

        Returns:
            The response as a dict with ``None`` fields excluded; the ``model``
            key is also dropped when no model was supplied.
        """
        data = self.model_dump(exclude_none=True)
        if self.model is None:
            data.pop("model", None)
        return data
