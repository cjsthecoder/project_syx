"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the OpenAI embedding provider.

Covers the pure response-parsing and rate-limit backoff helpers extracted from
``embed`` plus the end-to-end ``embed``/``embed_query`` behavior (success,
empty-input short-circuit, rate-limit retry-then-success, timeout retry, and
retry exhaustion) using a fake OpenAI client. The only faked boundary is the
SDK client (``OpenAI``) and the ``time.sleep``/``random`` backoff calls.
"""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import app.embedding.providers.openai_provider as provider_mod
import pytest
from app.embedding.providers.openai_provider import OpenAIEmbeddingProvider


def _make_provider(monkeypatch, create_side_effect):
    monkeypatch.setattr(
        provider_mod, "get_settings", lambda: SimpleNamespace(embedding_request_timeout_s=10.0)
    )
    monkeypatch.setattr(
        provider_mod, "get_active_embedding_model", lambda: "text-embedding-3-small"
    )
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


# ----- _is_rate_limit_error -----


def test_is_rate_limit_error_status_code_429():
    assert OpenAIEmbeddingProvider._is_rate_limit_error(_RateLimitError("x")) is True


def test_is_rate_limit_error_non_numeric_status_falls_back_to_message():
    exc = Exception("429 Too Many Requests")
    exc.status_code = "not-a-number"  # int() raises -> message-text detection
    assert OpenAIEmbeddingProvider._is_rate_limit_error(exc) is True


def test_is_rate_limit_error_false_for_unrelated():
    assert OpenAIEmbeddingProvider._is_rate_limit_error(Exception("network down")) is False


# ----- _is_timeout_error -----


def test_is_timeout_error():
    assert OpenAIEmbeddingProvider._is_timeout_error(Exception("Request timed out")) is True
    assert OpenAIEmbeddingProvider._is_timeout_error(Exception("nope")) is False


# ----- _extract_retry_after_seconds -----


def test_extract_retry_after_from_dict_headers():
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "12"}))
    assert OpenAIEmbeddingProvider._extract_retry_after_seconds(exc) == 12.0


def test_extract_retry_after_from_object_headers():
    class _Headers:
        def get(self, key):
            return "5" if key == "retry-after" else None

    exc = SimpleNamespace(response=SimpleNamespace(headers=_Headers()))
    assert OpenAIEmbeddingProvider._extract_retry_after_seconds(exc) == 5.0


def test_extract_retry_after_header_parse_error_falls_through(caplog):
    caplog.set_level(logging.DEBUG)

    class _BadHeaders:
        def get(self, key):
            return "not-a-float"

    exc = SimpleNamespace(response=SimpleNamespace(headers=_BadHeaders()))
    # float("not-a-float") raises -> logged -> no "try again in Ns" hint -> None.
    assert OpenAIEmbeddingProvider._extract_retry_after_seconds(exc) is None
    assert any("retry-after header parse skipped" in r.message for r in caplog.records)


def test_extract_retry_after_from_message_hint():
    exc = Exception("Rate limit reached, try again in 3.5s. Contact us.")
    assert OpenAIEmbeddingProvider._extract_retry_after_seconds(exc) == 3.5


def test_extract_retry_after_none_when_no_hint():
    assert OpenAIEmbeddingProvider._extract_retry_after_seconds(Exception("boom")) is None


# ----- _sleep_quietly -----


def test_sleep_quietly_logs_when_interrupted(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    provider, _client = _make_provider(monkeypatch, create_side_effect=[])

    def _raise(_s):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(provider_mod.time, "sleep", _raise)
    provider._sleep_quietly(0.1, model="m", phase="general")  # must not raise
    assert any("sleep interrupted" in r.message for r in caplog.records)


# ----- _rate_limit_base_wait_seconds -----


def test_rate_limit_base_wait_honors_retry_after_hint():
    exc = Exception("Rate limit reached, try again in 7s")
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 3) == 7.0


def test_rate_limit_base_wait_exponential_without_hint():
    exc = Exception("rate limit")
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 1) == 0.6 * (2**0)
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 2) == 0.6 * (2**1)


def test_rate_limit_base_wait_caps_backoff():
    exc = Exception("rate limit")
    # Attempt index is capped at 5, so attempts beyond that stay at 0.6 * 2**5.
    assert OpenAIEmbeddingProvider._rate_limit_base_wait_seconds(exc, 20) == 0.6 * (2**5)


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
    provider, _client = _make_provider(monkeypatch, create_side_effect=RuntimeError("boom"))
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="embedding provider failed after retries"):
        provider.embed(["x"], retries=1)


def test_embed_logs_timeout_then_retries(monkeypatch):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[1.0])])
    provider, client = _make_provider(
        monkeypatch, create_side_effect=[TimeoutError("Request timed out"), resp]
    )
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    result = provider.embed(["x"])

    assert result.vectors == [[1.0]]
    assert client.embeddings.create.call_count == 2


def test_embed_raises_after_rate_limit_retries_exhausted(monkeypatch):
    provider, _client = _make_provider(monkeypatch, create_side_effect=_RateLimitError("slow"))
    monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="rate_limit_retries=0"):
        provider.embed(["x"], rate_limit_retries=0)


def test_embed_query_returns_first_vector(monkeypatch):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[9.0, 8.0])])
    provider, _client = _make_provider(monkeypatch, create_side_effect=[resp])
    assert provider.embed_query("q") == [9.0, 8.0]


def test_embed_query_empty_when_no_vectors(monkeypatch):
    resp = SimpleNamespace(data=[])
    provider, _client = _make_provider(monkeypatch, create_side_effect=[resp])
    assert provider.embed_query("q") == []
