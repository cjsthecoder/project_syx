"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Error handling utilities for Syx AGI Chatbot Framework.

This module provides custom exceptions and error handling utilities.
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from .logging import get_logger

logger = get_logger()  # Use single shared logger


class SyxError(Exception):
    """Base exception for Syx application errors."""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class LLMError(SyxError):
    """Exception raised for LLM-related errors."""
    pass


class ConfigurationError(SyxError):
    """Exception raised for configuration errors."""
    pass


class MemoryError(SyxError):
    """Exception raised for memory-related errors."""
    pass


class RAGError(SyxError):
    """Exception raised for RAG-related errors."""
    pass


class ProjectError(SyxError):
    """Exception raised for project-related errors."""
    pass


# Error codes
ERROR_CODES = {
    "MISSING_API_KEY": "OpenAI API key is not configured",
    "INVALID_API_KEY": "OpenAI API key is invalid",
    "LLM_UNAVAILABLE": "LLM service is unavailable",
    "LLM_TIMEOUT": "LLM request timed out",
    "LLM_QUOTA_EXCEEDED": "LLM quota exceeded",
    "CONVERSATION_NOT_FOUND": "Conversation not found",
    "PROJECT_NOT_FOUND": "Project not found",
    "MEMORY_FULL": "Memory storage is full",
    "RAG_INDEX_ERROR": "RAG index error",
    "RAG_SEARCH_ERROR": "RAG search error",
    "CLEANUP_FAILED": "Memory cleanup failed",
    "VALIDATION_ERROR": "Request validation error",
    "INTERNAL_ERROR": "Internal server error"
}


def create_error_response(
    error: Exception,
    error_code: Optional[str] = None,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
) -> HTTPException:
    """
    Create a standardized error response.
    
    Args:
        error: The exception that occurred
        error_code: Optional error code
        status_code: HTTP status code
        
    Returns:
        HTTPException with standardized format
    """
    if isinstance(error, SyxError):
        error_code = error.error_code or error_code
        message = error.message
        details = error.details
    else:
        message = str(error)
        details = {}
    
    # Log the error
    logger.error(f"Error {error_code}: {message}", extra={"error_code": error_code, "details": details})
    
    return HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "error": message,
            "error_code": error_code,
            "details": details
        }
    )


def handle_llm_error(error: Exception) -> HTTPException:
    """Handle LLM-related errors."""
    if "api key" in str(error).lower():
        return create_error_response(
            error,
            error_code="MISSING_API_KEY",
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    elif "timeout" in str(error).lower():
        return create_error_response(
            error,
            error_code="LLM_TIMEOUT",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT
        )
    elif "quota" in str(error).lower():
        return create_error_response(
            error,
            error_code="LLM_QUOTA_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )
    else:
        return create_error_response(
            error,
            error_code="LLM_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


def handle_validation_error(error: Exception) -> HTTPException:
    """Handle validation errors."""
    return create_error_response(
        error,
        error_code="VALIDATION_ERROR",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


def handle_memory_error(error: Exception) -> HTTPException:
    """Handle memory-related errors."""
    return create_error_response(
        error,
        error_code="MEMORY_FULL",
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE
    )


def handle_rag_error(error: Exception) -> HTTPException:
    """Handle RAG-related errors."""
    return create_error_response(
        error,
        error_code="RAG_SEARCH_ERROR",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE
    )


def handle_project_error(error: Exception) -> HTTPException:
    """Handle project-related errors."""
    return create_error_response(
        error,
        error_code="PROJECT_NOT_FOUND",
        status_code=status.HTTP_404_NOT_FOUND
    )


def get_error_message(error_code: str) -> str:
    """Get a human-readable error message for an error code."""
    return ERROR_CODES.get(error_code, "An unknown error occurred")


def log_error_context(
    error: Exception,
    context: Dict[str, Any],
    logger_name: str = "errors"
) -> None:
    """Log error with additional context."""
    context_logger = get_logger()  # Use single shared logger
    context_logger.error(
        f"Error occurred: {str(error)}",
        extra={
            "error_type": type(error).__name__,
            "error_message": str(error),
            **context
        },
        exc_info=True
    )
