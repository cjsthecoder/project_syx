"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Unit tests for app.utils.errors.

Covers the standardized error-response shape, status-code mapping for the
typed handlers, and the error-code message lookup.
"""

from fastapi import status

from app.utils.errors import (
    ConfigurationError,
    LLMError,
    MemoryError,
    ProjectError,
    RAGError,
    SyxError,
    create_error_response,
    get_error_message,
    handle_llm_error,
    handle_memory_error,
    handle_project_error,
    handle_rag_error,
    handle_validation_error,
)


def test_syxerror_stores_fields_with_default_details():
    err = SyxError("boom", error_code="X")
    assert err.message == "boom"
    assert err.error_code == "X"
    assert err.details == {}
    assert str(err) == "boom"


def test_typed_errors_subclass_syxerror():
    for cls in (LLMError, ConfigurationError, MemoryError, RAGError, ProjectError):
        assert issubclass(cls, SyxError)


def test_create_error_response_from_syxerror():
    err = SyxError("nope", error_code="PROJECT_NOT_FOUND", details={"id": "p1"})
    http = create_error_response(err)
    assert http.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert http.detail["success"] is False
    assert http.detail["error"] == "nope"
    assert http.detail["error_code"] == "PROJECT_NOT_FOUND"
    assert http.detail["details"] == {"id": "p1"}


def test_create_error_response_from_generic_exception():
    http = create_error_response(
        ValueError("bad value"),
        error_code="VALIDATION_ERROR",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
    assert http.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert http.detail["error"] == "bad value"
    assert http.detail["error_code"] == "VALIDATION_ERROR"
    assert http.detail["details"] == {}


def test_handle_llm_error_maps_api_key():
    http = handle_llm_error(Exception("Invalid API key provided"))
    assert http.status_code == status.HTTP_401_UNAUTHORIZED
    assert http.detail["error_code"] == "MISSING_API_KEY"


def test_handle_llm_error_maps_timeout():
    http = handle_llm_error(Exception("request timeout exceeded"))
    assert http.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert http.detail["error_code"] == "LLM_TIMEOUT"


def test_handle_llm_error_maps_quota():
    http = handle_llm_error(Exception("monthly quota reached"))
    assert http.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert http.detail["error_code"] == "LLM_QUOTA_EXCEEDED"


def test_handle_llm_error_default_unavailable():
    http = handle_llm_error(Exception("connection reset"))
    assert http.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert http.detail["error_code"] == "LLM_UNAVAILABLE"


def test_handle_validation_error():
    http = handle_validation_error(Exception("bad"))
    assert http.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert http.detail["error_code"] == "VALIDATION_ERROR"


def test_handle_memory_error():
    http = handle_memory_error(Exception("full"))
    assert http.status_code == status.HTTP_507_INSUFFICIENT_STORAGE
    assert http.detail["error_code"] == "MEMORY_FULL"


def test_handle_rag_error():
    http = handle_rag_error(Exception("search failed"))
    assert http.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert http.detail["error_code"] == "RAG_SEARCH_ERROR"


def test_handle_project_error():
    http = handle_project_error(Exception("missing"))
    assert http.status_code == status.HTTP_404_NOT_FOUND
    assert http.detail["error_code"] == "PROJECT_NOT_FOUND"


def test_get_error_message_known_and_unknown():
    assert get_error_message("PROJECT_NOT_FOUND") == "Project not found"
    assert get_error_message("DOES_NOT_EXIST") == "An unknown error occurred"
