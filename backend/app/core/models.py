"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Pydantic models for Syx AGI Chatbot Framework.

This module defines all request and response models for the API endpoints.
"""

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, timezone

# Set up module-level logger
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current moment with UTC tzinfo attached, used as the default for
        response/error timestamp fields.
    """
    return datetime.now(timezone.utc)


# Base Response Model
class BaseResponse(BaseModel):
    """Base envelope for successful API responses.

    Provides the success flag and server timestamp shared by all concrete
    response models; subclasses add their endpoint-specific payload fields.
    """
    success: bool = Field(default=True, description="Whether the request was successful")
    timestamp: datetime = Field(default_factory=utc_now, description="Response timestamp")


# Chat Models
class ChatRequest(BaseModel):
    """Request body for the chat endpoint.

    Carries the user message plus optional project/conversation context and a
    per-request model override. Field-level constraints and the schema example
    are defined below.
    """
    message: str = Field(..., min_length=1, max_length=200000, description="User message")
    project_id: Optional[str] = Field(default=None, description="Project context (stub)")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for context")
    model: Optional[str] = Field(default=None, description="Override model for this request")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Hello, how can you help me today?",
                "project_id": "default",
                "conversation_id": "conv_123",
                "model": "gpt-5.1"
            }
        }
    )


class ChatResponse(BaseResponse):
    """Response body for the chat endpoint.

    Extends :class:`BaseResponse` with the assistant reply and the model and
    token-usage metadata for the turn.
    """
    response: str = Field(..., description="AI response message")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID")
    llm_model: Optional[str] = Field(default=None, description="Model used for response")
    tokens_used: Optional[int] = Field(default=None, description="Tokens used in response")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "response": "Hello! I'm here to help you with any questions or tasks you have.",
                "conversation_id": "conv_123",
                "llm_model": "gpt-5.1",
                "tokens_used": 25,
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }
    )


# RAG Models
class RAGRequest(BaseModel):
    """Request body for the standalone RAG query endpoint.

    Holds the retrieval query, optional project scope, and a bounded result
    count used to size retrieval.
    """
    query: str = Field(..., min_length=1, max_length=2000, description="RAG query")
    project_id: Optional[str] = Field(default=None, description="Project context")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum number of results")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "What is machine learning?",
                "project_id": "default",
                "max_results": 5
            }
        }
    )


class RAGResponse(BaseResponse):
    """Response body for the RAG query endpoint.

    Extends :class:`BaseResponse` with the synthesized answer, the supporting
    source documents, and an optional confidence score.
    """
    response: str = Field(..., description="RAG response")
    sources: List[Dict[str, Any]] = Field(default=[], description="Source documents")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Response confidence")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "response": "Machine learning is a subset of artificial intelligence...",
                "sources": [
                    {"title": "ML Basics", "url": "https://example.com/ml", "score": 0.95}
                ],
                "confidence": 0.92,
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }
    )


# Project Models
class ProjectRequest(BaseModel):
    """Request body for project operations (select, create, toggle Daily RAG).

    All fields are optional; the populated combination determines which
    operation the endpoint performs.
    """
    project_id: Optional[str] = Field(default=None, description="Project ID to switch to")
    project_name: Optional[str] = Field(default=None, description="New project name")
    daily_rag_enabled: Optional[bool] = Field(default=None, description="Toggle per-project Daily RAG")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": "project_123",
                "project_name": "My New Project"
            }
        }
    )


class ProjectResponse(BaseResponse):
    """Response body for project operations.

    Extends :class:`BaseResponse` with a human-readable result message, the
    currently selected project, and the list of available projects.
    """
    response: str = Field(..., description="Project operation response")
    current_project: Optional[str] = Field(default=None, description="Current project ID")
    available_projects: List[str] = Field(default=[], description="List of available projects")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "response": "Switched to project 'My Project'",
                "current_project": "project_123",
                "available_projects": ["default", "project_123", "project_456"],
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }
    )


# Sleep Cycle Models
class SleepCycleRequest(BaseModel):
    """Request body for triggering a memory sleep cycle.

    Optionally scopes the cycle to one project and can force immediate cleanup
    rather than deferring to the scheduler.
    """
    project_id: Optional[str] = Field(default=None, description="Project to clean up")
    force_cleanup: bool = Field(default=False, description="Force immediate cleanup")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": "default",
                "force_cleanup": False
            }
        }
    )


class SleepCycleResponse(BaseResponse):
    """Response body for the sleep cycle endpoint.

    Extends :class:`BaseResponse` with a status message and optional cleanup
    metrics (items cleaned, before/after memory usage).
    """
    response: str = Field(..., description="Sleep cycle response")
    items_cleaned: Optional[int] = Field(default=None, description="Number of items cleaned")
    memory_usage_before: Optional[str] = Field(default=None, description="Memory usage before cleanup")
    memory_usage_after: Optional[str] = Field(default=None, description="Memory usage after cleanup")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "response": "Memory cleanup completed successfully",
                "items_cleaned": 150,
                "memory_usage_before": "2.5GB",
                "memory_usage_after": "1.8GB",
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }
    )


# Error Models
class ErrorResponse(BaseModel):
    """Standard error envelope returned for failed requests.

    Unlike :class:`BaseResponse`, ``success`` defaults to ``False``; carries an
    error message, an optional machine-readable error code, and structured
    details for clients to act on.
    """
    success: bool = Field(default=False, description="Request failed")
    error: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(default=None, description="Error code")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error details")
    timestamp: datetime = Field(default_factory=utc_now, description="Error timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error": "OpenAI API key not configured",
                "error_code": "MISSING_API_KEY",
                "details": {"field": "openai_api_key"},
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }
    )


# Health Check Models
class HealthResponse(BaseModel):
    """Response body for the health check endpoint.

    Reports overall service status plus identifying metadata and a per-
    dependency status map used by liveness/readiness probes.
    """
    status: str = Field(..., description="Service status")
    service: str = Field(default="syx-api", description="Service name")
    version: str = Field(default="1.0.0", description="Service version")
    timestamp: datetime = Field(default_factory=utc_now, description="Health check timestamp")
    dependencies: Dict[str, str] = Field(default={}, description="Dependency status")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "service": "syx-api",
                "version": "1.0.0",
                "timestamp": "2024-01-01T12:00:00Z",
                "dependencies": {
                    "openai": "connected",
                    "llm": "ready"
                }
            }
        }
    )
