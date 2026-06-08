"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
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
        """Initialize the error with a message and optional structured metadata.

        Args:
            message: Human-readable description of the failure.
            error_code: Stable machine-readable code identifying the failure
                category; used to look up canonical messages and shape API
                responses.
            details: Arbitrary structured context about the error; defaults to
                an empty dict when omitted.
        """
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
    """Map an LLM error to an HTTPException by inspecting its message.

    The error message is matched (case-insensitively) against known failure
    signatures (missing key, timeout, quota) and falls back to a generic
    service-unavailable response.

    Args:
        error: The LLM-related exception that occurred.

    Returns:
        An HTTPException with an appropriate status code and error code.
    """
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
    """Map a request validation error to a 422 HTTPException.

    Args:
        error: The validation-related exception that occurred.

    Returns:
        An HTTPException carrying the ``VALIDATION_ERROR`` code and a 422 status.
    """
    return create_error_response(
        error,
        error_code="VALIDATION_ERROR",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
    )


def handle_memory_error(error: Exception) -> HTTPException:
    """Map a memory storage error to a 507 HTTPException.

    Args:
        error: The memory-related exception that occurred.

    Returns:
        An HTTPException carrying the ``MEMORY_FULL`` code and a 507 status.
    """
    return create_error_response(
        error,
        error_code="MEMORY_FULL",
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE
    )


def handle_rag_error(error: Exception) -> HTTPException:
    """Map a RAG search/index error to a 503 HTTPException.

    Args:
        error: The RAG-related exception that occurred.

    Returns:
        An HTTPException carrying the ``RAG_SEARCH_ERROR`` code and a 503 status.
    """
    return create_error_response(
        error,
        error_code="RAG_SEARCH_ERROR",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE
    )


def handle_project_error(error: Exception) -> HTTPException:
    """Map a project lookup error to a 404 HTTPException.

    Args:
        error: The project-related exception that occurred.

    Returns:
        An HTTPException carrying the ``PROJECT_NOT_FOUND`` code and a 404 status.
    """
    return create_error_response(
        error,
        error_code="PROJECT_NOT_FOUND",
        status_code=status.HTTP_404_NOT_FOUND
    )


def get_error_message(error_code: str) -> str:
    """Get a human-readable error message for an error code.

    Args:
        error_code: A key from ``ERROR_CODES`` identifying the failure.

    Returns:
        The canonical message for the code, or a generic fallback message when
        the code is unknown.
    """
    return ERROR_CODES.get(error_code, "An unknown error occurred")


def log_error_context(
    error: Exception,
    context: Dict[str, Any],
    logger_name: str = "errors"
) -> None:
    """Log an error together with extra structured context and a traceback.

    Args:
        error: The exception to log; its type and message are recorded.
        context: Additional key/value fields merged into the log record's
            ``extra`` for downstream filtering and debugging.
        logger_name: Retained for call-site clarity; the shared application
            logger is used regardless of this value.
    """
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
