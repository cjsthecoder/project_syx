"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the LLM and embedding provider factories.

Provider classes are replaced with lightweight fakes so factory behavior
(provider selection, singleton caching, reset, key/provider validation) is
verified without constructing real SDK clients or touching the network.
"""

import importlib.util
import os
import sys
import types
from typing import get_type_hints

import app.embedding
import app.llm_model.factory as llm_factory
import pytest
from app.llm_model.base import LLMClient


class _FakeLLMProvider:
    def __init__(self, *, api_key, default_model, timeout_s):
        self.api_key = api_key
        self.default_model = default_model
        self.timeout_s = timeout_s

    def generate_chat(self, **_kwargs):
        raise NotImplementedError

    def stream_chat(self, **_kwargs):
        raise NotImplementedError

    def generate_response(self, **_kwargs):
        raise NotImplementedError

    def generate_response_research(self, **_kwargs):
        raise NotImplementedError


class _FakeEmbeddingProvider:
    def __init__(self, *, api_key=None):
        self.api_key = api_key


class _FakeSTProvider:
    def __init__(self):
        self.kind = "sentence_transformers"


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(llm_factory, "OpenAILLMProvider", _FakeLLMProvider)
    llm_factory.reset_llm_clients()
    yield llm_factory
    llm_factory.reset_llm_clients()


@pytest.fixture
def fake_embedding(monkeypatch):
    # Other test modules permanently install stub `app.embedding.factory`,
    # `numpy`, and `faiss` modules into sys.modules. To get the real factory
    # decision logic without triggering its heavy provider imports (which would
    # fail against the stubbed numpy), inject fake provider modules first and
    # then exec the real factory source. All entries are restored by monkeypatch.
    fake_openai_mod = types.ModuleType("app.embedding.providers.openai_provider")
    fake_openai_mod.OpenAIEmbeddingProvider = _FakeEmbeddingProvider
    fake_st_mod = types.ModuleType("app.embedding.providers.sentence_transformers_provider")
    fake_st_mod.SentenceTransformersEmbeddingProvider = _FakeSTProvider
    monkeypatch.setitem(sys.modules, "app.embedding.providers.openai_provider", fake_openai_mod)
    monkeypatch.setitem(
        sys.modules, "app.embedding.providers.sentence_transformers_provider", fake_st_mod
    )

    factory_path = os.path.join(os.path.dirname(app.embedding.__file__), "factory.py")
    spec = importlib.util.spec_from_file_location("app.embedding.factory", factory_path)
    real = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.embedding.factory", real)
    spec.loader.exec_module(real)
    real.reset_embedding_client()
    yield real
    real.reset_embedding_client()


def test_llm_client_is_cached_singleton(fake_llm, settings_override):
    settings_override(model_name="gpt-main")
    c1 = fake_llm.get_llm_client()
    c2 = fake_llm.get_llm_client()
    assert c1 is c2
    assert isinstance(c1, LLMClient)
    assert isinstance(c1, _FakeLLMProvider)
    assert c1.default_model == "gpt-main"


def test_llm_factory_public_return_types_are_provider_agnostic():
    assert get_type_hints(llm_factory.get_llm_client)["return"] is LLMClient
    assert get_type_hints(llm_factory.get_llm_client_mini)["return"] is LLMClient


def test_main_and_mini_clients_are_distinct(fake_llm, settings_override):
    settings_override(model_name="gpt-main", llm_mini_model="gpt-mini")
    main = fake_llm.get_llm_client()
    mini = fake_llm.get_llm_client_mini()
    assert main is not mini
    assert isinstance(main, LLMClient)
    assert isinstance(mini, LLMClient)
    assert main.default_model == "gpt-main"
    assert mini.default_model == "gpt-mini"


def test_reset_llm_clients_forces_new_instance(fake_llm):
    first = fake_llm.get_llm_client()
    fake_llm.reset_llm_clients()
    second = fake_llm.get_llm_client()
    assert first is not second


def test_unknown_provider_falls_back_to_openai(fake_llm, settings_override, caplog):
    settings_override(llm_provider="anthropic")
    client = fake_llm.get_llm_client()
    assert isinstance(client, _FakeLLMProvider)
    assert any(
        "Unsupported LLM provider 'anthropic'; falling back to openai" in r.message
        for r in caplog.records
    )


def test_embedding_openai_requires_key(fake_embedding, settings_override):
    settings_override(embedding_provider="openai", openai_api_key="")
    with pytest.raises(RuntimeError):
        fake_embedding.get_embedding_client()


def test_embedding_openai_with_key(fake_embedding, settings_override):
    settings_override(embedding_provider="openai", openai_api_key="sk-test")
    client = fake_embedding.get_embedding_client()
    assert isinstance(client, _FakeEmbeddingProvider)
    # Cached singleton.
    assert fake_embedding.get_embedding_client() is client


def test_embedding_sentence_transformers(fake_embedding, settings_override):
    settings_override(embedding_provider="sentence_transformers")
    client = fake_embedding.get_embedding_client()
    assert isinstance(client, _FakeSTProvider)


def test_embedding_unknown_provider_raises(fake_embedding, settings_override):
    settings_override(embedding_provider="pinecone")
    with pytest.raises(RuntimeError):
        fake_embedding.get_embedding_client()


def test_reset_embedding_client(fake_embedding, settings_override):
    settings_override(embedding_provider="sentence_transformers")
    first = fake_embedding.get_embedding_client()
    fake_embedding.reset_embedding_client()
    second = fake_embedding.get_embedding_client()
    assert first is not second
