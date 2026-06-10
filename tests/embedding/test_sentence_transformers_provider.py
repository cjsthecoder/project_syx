"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the sentence-transformers embedding provider.

The real ``SentenceTransformer`` is patched with a lightweight fake so no model
weights are downloaded or loaded. Covers eager model load + caching, the
empty-input short-circuit, non-string coercion, successful encoding, the
encode-failure -> RuntimeError path, and ``embed_query``.
"""

from types import SimpleNamespace

import app.embedding.providers.sentence_transformers_provider as provider_mod
import pytest
from app.embedding.providers.sentence_transformers_provider import (
    SentenceTransformersEmbeddingProvider,
)


class _Encoded:
    """Stand-in for the numpy array returned by ``SentenceTransformer.encode``."""

    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


class _FakeST:
    """Records constructions/encode calls; never touches the network."""

    constructed = []

    def __init__(self, model_id, *, raise_on_encode=False):
        self.model_id = model_id
        self.raise_on_encode = raise_on_encode
        self.encode_calls = []
        _FakeST.constructed.append(model_id)

    def encode(self, texts, **kwargs):
        if self.raise_on_encode:
            raise RuntimeError("encode boom")
        self.encode_calls.append((list(texts), kwargs))
        return _Encoded([[float(len(t))] for t in texts])


@pytest.fixture(autouse=True)
def _reset_constructed():
    _FakeST.constructed = []
    yield
    _FakeST.constructed = []


def _patch_env(monkeypatch, *, st_factory=None, model="all-MiniLM-L6-v2"):
    monkeypatch.setattr(provider_mod, "get_active_embedding_model", lambda: model)
    monkeypatch.setattr(
        provider_mod,
        "get_settings",
        lambda: SimpleNamespace(embedding_provider="sentence_transformers"),
    )
    factory = st_factory or (lambda model_id: _FakeST(model_id))
    monkeypatch.setattr(provider_mod, "SentenceTransformer", factory)


def test_init_eagerly_loads_active_model(monkeypatch):
    _patch_env(monkeypatch, model="my-model")
    SentenceTransformersEmbeddingProvider()
    assert _FakeST.constructed == ["my-model"]  # loaded once at construction


def test_get_model_caches_by_id(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    # Construction already loaded "m1"; a repeat request must not reconstruct.
    first = provider._get_model("m1")
    second = provider._get_model("m1")
    assert first is second
    assert _FakeST.constructed == ["m1"]


def test_get_model_blank_falls_back_to_active(monkeypatch):
    _patch_env(monkeypatch, model="active-model")
    provider = SentenceTransformersEmbeddingProvider()
    model = provider._get_model("")  # falsy id -> active model
    assert model.model_id == "active-model"


def test_embed_empty_short_circuits(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    res = provider.embed([])
    assert res.vectors == []
    assert res.model == "m1"


def test_embed_success_returns_normalized_vectors(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    res = provider.embed(["ab", "cde"], model="m1")
    assert res.model == "m1"
    assert res.vectors == [[2.0], [3.0]]  # _Encoded mapped len(text)
    # encode invoked with the normalization flags the provider relies on.
    model = provider._get_model("m1")
    texts, kwargs = model.encode_calls[-1]
    assert texts == ["ab", "cde"]
    assert kwargs["normalize_embeddings"] is True
    assert kwargs["convert_to_numpy"] is True
    assert kwargs["show_progress_bar"] is False


def test_embed_coerces_non_string_items(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    res = provider.embed(["ok", None, 123])
    # None/123 coerced to "" (len 0) before encoding.
    assert res.vectors == [[2.0], [0.0], [0.0]]


def test_embed_failure_raises_runtime_error(monkeypatch):
    _patch_env(
        monkeypatch,
        st_factory=lambda model_id: _FakeST(model_id, raise_on_encode=True),
        model="m1",
    )
    provider = SentenceTransformersEmbeddingProvider()
    with pytest.raises(RuntimeError, match="sentence-transformers embedding failed"):
        provider.embed(["text"])


def test_embed_query_returns_first_vector(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    assert provider.embed_query("hello") == [5.0]  # len("hello")


def test_embed_query_empty_when_no_vectors(monkeypatch):
    _patch_env(monkeypatch, model="m1")
    provider = SentenceTransformersEmbeddingProvider()
    # None text -> embed(["" ]) -> _Encoded([[0.0]]) -> first vector [0.0].
    assert provider.embed_query(None) == [0.0]
