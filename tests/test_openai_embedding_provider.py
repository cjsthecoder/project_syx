"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for the OpenAI embedding provider.

Covers the pure response-parsing and rate-limit backoff helpers extracted from
``embed`` plus the end-to-end ``embed``/``embed_query`` behavior (success,
empty-input short-circuit, and rate-limit retry-then-success) using a fake
OpenAI client.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import app.embedding.providers.openai_provider as provider_mod
from app.embedding.providers.openai_provider import OpenAIEmbeddingProvider


def _make_provider(monkeypatch, create_side_effect):
    monkeypatch.setattr(
        provider_mod, "get_settings", lambda: SimpleNamespace(embedding_request_timeout_s=10.0)
    )
    monkeypatch.setattr(provider_mod, "get_active_embedding_model", lambda: "text-embedding-3-small")
    with patch.object(provider_mod, "OpenAI") as MockOpenAI:
        client = MockOpenAI.return_value
        client.embeddings.create.side_effect = create_side_effect
        provider = OpenAIEmbeddingProvider(api_key="test-key")
    return provider, client


class _RateLimitError(Exception):
    """Fake SDK error recognized as rate limiting via its status code."""

    status_code = 429


# ----- _parse_embedding_vectors -----


def test_parse_vectors_from_object_data():
    resp = SimpleNamespace(
        data=[SimpleNamespace(embedding=[1.0, 2.0]), SimpleNamespace(embedding=[3.0, 4.0])]
    )
    assert OpenAIEmbeddingProvider._parse_embedding_vectors(resp) == [[1.0, 2.0], [3.0, 4.0]]


def test_parse_vectors_falls_back_to_model_dump():
    class _Resp:
        def model_dump(self, mode="python"):
            return {"data": [{"embedding": [5.0, 6.0]}]}

    assert OpenAIEmbeddingProvider._parse_embedding_vectors(_Resp()) == [[5.0, 6.0]]


def test_parse_vectors_skips_items_without_list_embedding():
    resp = SimpleNamespace(
        data=[
            SimpleNamespace(embedding=[1.0]),
            SimpleNamespace(embedding=None),
            {"no_embedding": True},
        ]
    )
    assert OpenAIEmbeddingProvider._parse_embedding_vectors(resp) == [[1.0]]


def test_parse_vectors_empty_data():
    assert OpenAIEmbeddingProvider._parse_embedding_vectors(SimpleNamespace(data=[])) == []


# ----- _rate_limit_base_wait_seconds -----


def test_rate_limit_base_wait_honors_retry_after_hint():
    exc = Exception("Rate limit reached, try again in 7s")
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 3) == 7.0


def test_rate_limit_base_wait_exponential_without_hint():
    exc = Exception("rate limit")
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 1) == 0.6 * (2 ** 0)
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 2) == 0.6 * (2 ** 1)


def test_rate_limit_base_wait_caps_backoff():
    exc = Exception("rate limit")
    # Attempt index is capped at 5, so attempts beyond that stay at 0.6 * 2**5.
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 20) == 0.6 * (2 ** 5)


# ----- embed / embed_query -----


def test_embed_empty_input_short_circuits(monkeypatch):
    provider, client = _make_provider(monkeypatch, create_side_effect=[])
    result = provider.embed([])
    assert result.vectors == []
    assert result.model == "text-embedding-3-small"
    client.embeddings.create.assert_not_called()


def test_embed_success_returns_vectors(monkeypatch):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
    provider, client = _make_provider(monkeypatch, create_side_effect=[resp])
    result = provider.embed(["hello"])
    assert result.vectors == [[0.1, 0.2]]
    assert result.model == "text-embedding-3-small"
    assert client.embeddings.create.call_count == 1


def test_embed_retries_after_rate_limit_then_succeeds(monkeypatch):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[0.5])])
    provider, client = _make_provider(
        monkeypatch, create_side_effect=[_RateLimitError("slow down"), resp]
    )
    sleeps = []
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: sleeps.append(s))

    result = provider.embed(["hi"])

    assert result.vectors == [[0.5]]
    assert client.embeddings.create.call_count == 2
    assert len(sleeps) == 1


def test_embed_raises_after_exhausting_retries(monkeypatch):
    provider, _client = _make_provider(
        monkeypatch, create_side_effect=RuntimeError("boom")
    )
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="embedding provider failed after retries"):
        provider.embed(["x"], retries=1)


def test_embed_query_returns_first_vector(monkeypatch):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[9.0, 8.0])])
    provider, _client = _make_provider(monkeypatch, create_side_effect=[resp])
    assert provider.embed_query("q") == [9.0, 8.0]


def test_embed_query_empty_when_no_vectors(monkeypatch):
    resp = SimpleNamespace(data=[])
    provider, _client = _make_provider(monkeypatch, create_side_effect=[resp])
    assert provider.embed_query("q") == []
