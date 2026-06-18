"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Contract tests for the chat API router.

These cover request validation and the non-LLM endpoints (health, stats). The
full LLM chat pipeline is intentionally out of scope here; ``get_llm_health`` is
patched so health behavior is deterministic and offline.
"""

from types import SimpleNamespace

import pytest
from app.api import chat as chat_module
from app.core.config import get_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(chat_module.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _llm_configured(monkeypatch):
    monkeypatch.setattr(chat_module, "validate_active_llm_key", lambda: True)
    monkeypatch.setattr(
        chat_module,
        "active_llm_key_status",
        lambda: {
            "provider": "openai",
            "setting": "OPENAI_API_KEY",
            "dependency": "openai",
            "status": "configured",
        },
    )


# ---------------------------------------------------------------------------
# Orchestration fakes
#
# These tests pin the behavior of ``chat_endpoint`` / ``chat_stream`` (prompt
# assembly order, persistence calls, chit-chat routing, streaming output, and
# turn instrumentation) without exercising the real LLM, memory, or pipeline
# internals. The pipeline has its own unit tests; here we want a safety net for
# the router orchestration so it can be refactored with confidence.
# ---------------------------------------------------------------------------

CHITCHAT_MESSAGE = "__chitchat__"


class FakePipeline:
    """Drop-in replacement for ``ChatPipeline`` that returns canned values.

    Routing namespace is derived from the message: ``CHITCHAT_MESSAGE`` yields
    the ``chitchat`` namespace so chit-chat forget/skip-tagger behavior can be
    asserted; everything else routes to ``other``.
    """

    persist: list = []
    enforced_models: list = []

    def __init__(self, settings):
        self.settings = settings

    def build_conversation_history(self, project_id):
        return [
            {"role": "user", "content": "earlier user"},
            {"role": "assistant", "content": "earlier assistant"},
        ]

    def load_project_prompts(self, project_id):
        return ("BASE_SYS", "ASSISTANT_HINT", 0.7)

    def compute_rag_context(self, *, project_id, message, preview, msg_id, conversation_history):
        ns = "chitchat" if message == CHITCHAT_MESSAGE else "other"
        metrics = {
            "route": ns.upper(),
            "rag_enabled": False,
            "retrieved_count": 0,
            "kept_count": 0,
            "expanded_unique_chunks_after_merge": 0,
            "rag_tokens_injected_est": 0,
            "final_context_clipped": False,
        }
        return ("RAG_CTX", ns, metrics)

    def apply_rag_guidance(self, base_system_prompt, rag_system_prompt):
        return base_system_prompt

    def enforce_model_whitelist(self, requested_model):
        FakePipeline.enforced_models.append(requested_model)
        return SimpleNamespace(
            provider_id="openai",
            selection_value=requested_model or "openai/gpt-test",
            main_model="gpt-test",
            mini_model="gpt-mini",
            builder_model="gpt-mini",
            tagger_model="gpt-mini",
            dream_model="gpt-test",
        )

    def previous_pair_text(self, conversation_history):
        return "PREV_PAIR"

    def persist_user(self, project_id, message):
        FakePipeline.persist.append(("user", project_id, message))

    def persist_assistant(
        self,
        project_id,
        message,
        namespace,
        *,
        user_text_for_tagging=None,
        previous_pair_text_for_tagging=None,
        forget=False,
        skip_tagger=False,
    ):
        FakePipeline.persist.append(
            ("assistant", project_id, message, namespace, forget, skip_tagger)
        )

    def build_llm_messages(
        self,
        *,
        base_system_prompt,
        assistant_hint,
        rag_system_prompt,
        conversation_history,
        user_message,
    ):
        return [{"role": "user", "content": user_message}]


class FakeMemoryManager:
    """Records the direct persistence calls made by the non-streaming endpoint."""

    def __init__(self, calls):
        self.calls = calls

    def append_user_message(self, project_id, message):
        self.calls.append(("user", project_id, message))

    def append_assistant_message(
        self,
        project_id,
        message,
        *,
        namespace=None,
        user_text_for_tagging=None,
        previous_pair_text_for_tagging=None,
        forget=False,
        skip_tagger=False,
    ):
        self.calls.append(("assistant", project_id, message, namespace, forget, skip_tagger))


class FakeInstrumentation:
    """No-op instrumentation that records turn-end metadata for assertions."""

    def __init__(self, turns):
        self.turns = turns

    def start_turn(self, *, turn_id, user_meta):
        return None

    def end_turn(self, *, output_meta):
        self.turns.append(output_meta)

    def start_invocation(self, *, purpose, model, meta=None):
        return "inv-1"

    def end_invocation(self, invocation_id, *, usage=None, timing=None):
        return None

    def record_stage(self, *args, **kwargs):
        return None


@pytest.fixture
def chat_env(monkeypatch):
    """Patch the chat router's collaborators with recording fakes.

    Returns a namespace exposing the recorded ``persist`` (streaming pipeline),
    ``mem`` (non-streaming direct persistence), ``turns`` (turn-end meta), and
    ``context_tokens`` calls.
    """
    FakePipeline.persist = []
    FakePipeline.enforced_models = []
    mem_calls: list = []
    turns: list = []
    context_tokens: list = []

    monkeypatch.setattr(chat_module, "ChatPipeline", FakePipeline)
    monkeypatch.setattr(chat_module, "get_memory_manager", lambda: FakeMemoryManager(mem_calls))
    monkeypatch.setattr(chat_module, "get_instrumentation", lambda: FakeInstrumentation(turns))
    monkeypatch.setattr(
        chat_module,
        "set_last_context_tokens",
        lambda pid, tokens: context_tokens.append((pid, tokens)),
    )

    return SimpleNamespace(
        persist=FakePipeline.persist,
        enforced_models=FakePipeline.enforced_models,
        mem=mem_calls,
        turns=turns,
        context_tokens=context_tokens,
    )


def test_chat_rejects_empty_message(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_rejects_missing_message(client):
    resp = client.post("/chat", json={"project_id": "p1"})
    assert resp.status_code == 422


def test_chat_health_healthy(client, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "get_llm_health",
        lambda: {"status": "healthy", "model": "gpt-test"},
    )
    resp = client.get("/chat/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["service"] == "chat"
    assert body["model"] == "gpt-test"


def test_chat_health_unhealthy(client, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "get_llm_health",
        lambda: {"status": "unhealthy", "error": "no key"},
    )
    resp = client.get("/chat/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["service"] == "chat"


def test_chat_stats_shape(client):
    resp = client.get("/chat/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"conversations", "messages", "memory_mode", "features"}
    assert body["memory_mode"] == "persistent"


# ---------------------------------------------------------------------------
# /chat (non-streaming) orchestration
# ---------------------------------------------------------------------------


def test_chat_happy_path_returns_response_and_persists(client, chat_env, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {
            "success": True,
            "response": "the answer",
            "llm_model": "gpt-test",
            "tokens_used": 42,
        },
    )

    resp = client.post(
        "/chat",
        json={"message": "hello there", "project_id": "p1", "conversation_id": "c1"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "the answer"
    assert body["conversation_id"] == "c1"
    assert body["llm_model"] == "gpt-test"
    assert body["tokens_used"] == 42

    # Model whitelist enforced, user then assistant persisted in order.
    assert chat_env.enforced_models == [None]
    assert chat_env.mem[0] == ("user", "p1", "hello there")
    assistant = chat_env.mem[1]
    assert assistant[0] == "assistant"
    assert assistant[1] == "p1"
    assert assistant[2] == "the answer"
    assert assistant[3] == "other"  # namespace
    assert assistant[4] is False  # forget
    assert assistant[5] is False  # skip_tagger

    # Context-token stats recorded for the project; turn closed.
    assert chat_env.context_tokens and chat_env.context_tokens[0][0] == "p1"
    assert chat_env.turns and chat_env.turns[0]["route"] == "OTHER"


def test_chat_chitchat_sets_forget_and_skip_tagger(client, chat_env, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "ok", "llm_model": "m", "tokens_used": 1},
    )

    resp = client.post(
        "/chat",
        json={"message": CHITCHAT_MESSAGE, "project_id": "p1", "conversation_id": "c1"},
    )

    assert resp.status_code == 200
    assistant = chat_env.mem[1]
    assert assistant[3] == "chitchat"  # namespace
    assert assistant[4] is True  # forget
    assert assistant[5] is True  # skip_tagger


def test_chat_without_project_skips_persistence(client, chat_env, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "ok", "llm_model": "m", "tokens_used": 1},
    )

    resp = client.post("/chat", json={"message": "hi", "conversation_id": "c1"})

    assert resp.status_code == 200
    assert chat_env.mem == []
    assert chat_env.context_tokens == []


def test_chat_missing_provider_key_returns_503_before_persistence(client, chat_env, monkeypatch):
    monkeypatch.setattr(chat_module, "validate_active_llm_key", lambda: False)
    monkeypatch.setattr(
        chat_module,
        "active_llm_key_status",
        lambda: {
            "provider": "anthropic",
            "setting": "ANTHROPIC_API_KEY",
            "dependency": "anthropic",
            "status": "missing",
        },
    )

    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})

    assert resp.status_code == 503
    assert resp.json()["detail"]["error_code"] == "llm_not_configured"
    assert resp.json()["detail"]["details"]["dependency"] == "anthropic"
    assert chat_env.mem == []


def test_chat_llm_failure_returns_500(client, chat_env, monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": False, "error": "boom"},
    )

    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})

    assert resp.status_code == 500
    assert resp.json()["detail"]["error_code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# /chat/stream orchestration
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self):
        self.prompt_tokens_reported = 10
        self.completion_tokens_reported = 5
        self.total_tokens_reported = 15
        self.usage_is_estimate = False
        self.extra_usage = None


class _FakeStreamClient:
    def stream_chat(self, *, messages, model, temperature, max_completion_tokens):
        yield ("Hello", None)
        yield (" world", None)
        yield (None, _FakeUsage())


def test_chat_stream_true_streaming(client, chat_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _FakeStreamClient())

    resp = client.post(
        "/chat/stream",
        json={"message": "hi", "project_id": "p1", "conversation_id": "c1"},
    )

    assert resp.status_code == 200
    assert "Hello world" in resp.text
    assert "::event: done" in resp.text

    # User persisted up-front; assistant persisted with the full streamed text.
    assert ("user", "p1", "hi") in chat_env.persist
    assistant = [c for c in chat_env.persist if c[0] == "assistant"]
    assert assistant and assistant[0][2] == "Hello world"
    assert assistant[0][3] == "other"  # namespace
    assert chat_env.turns and chat_env.turns[0]["streaming"] is True


def test_chat_stream_disabled_falls_back_to_simulated_stream(client, chat_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "streaming_enabled", False)
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "abc", "llm_model": "m", "tokens_used": 1},
    )

    resp = client.post(
        "/chat/stream",
        json={"message": "hi", "project_id": "p1", "conversation_id": "c1"},
    )

    assert resp.status_code == 200
    assert "abc" in resp.text
    assert "::event: done" in resp.text
    assistant = [c for c in chat_env.persist if c[0] == "assistant"]
    assert assistant and assistant[0][2] == "abc"


def test_chat_stream_missing_openai_key_returns_503_before_persistence(
    client, chat_env, monkeypatch
):
    monkeypatch.setattr(chat_module, "validate_active_llm_key", lambda: False)

    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )

    assert resp.status_code == 503
    assert resp.json()["detail"]["error_code"] == "llm_not_configured"
    assert chat_env.persist == []


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_build_stream_usage_payload_prefers_provider_usage():
    provider = {"total_tokens_reported": 99, "usage_is_estimate": False}
    out = chat_module._build_stream_usage_payload(provider, [{"content": "x"}], "abc")
    assert out is provider


def test_build_stream_usage_payload_estimates_when_no_provider():
    out = chat_module._build_stream_usage_payload(
        None, [{"role": "user", "content": "hello there"}], "a longer reply"
    )
    assert out["usage_is_estimate"] is True
    assert out["total_tokens_reported"] > 0


def test_build_stream_usage_payload_zeroes_nonpositive_estimate():
    # Empty prompt + empty completion -> estimate 0 -> zeroed payload.
    out = chat_module._build_stream_usage_payload(None, [], "")
    assert out["total_tokens_reported"] == 0
    assert out["usage_is_estimate"] is True


def test_update_context_token_stats_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        chat_module, "count_tokens", lambda _t: (_ for _ in ()).throw(RuntimeError("tok down"))
    )
    chat_module._update_context_token_stats(
        project_id="p1",
        conversation_history=[{"content": "x"}],
        message="m",
        response_text="r",
        msg_id="mid",
    )
    assert any("context_tokens update failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# /chat additional branches
# ---------------------------------------------------------------------------


def test_chat_llm_error_maps_to_llm_handler(client, chat_env, monkeypatch):
    # An error message mentioning "llm" routes through handle_llm_error (503).
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": False, "error": "llm provider exploded"},
    )
    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})
    assert resp.status_code == 503


def test_chat_persist_failure_is_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "ok", "llm_model": "m", "tokens_used": 1},
    )

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(FakeMemoryManager, "append_user_message", boom)
    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})
    assert resp.status_code == 200  # persistence failure does not fail the turn
    assert any("Persist failed" in r.message for r in caplog.records)


def test_chat_prompt_debug_dump_failure_is_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "ok", "llm_model": "m", "tokens_used": 1},
    )

    def boom(**kwargs):
        raise RuntimeError("debug write failed")

    monkeypatch.setattr(chat_module, "dump_prompt_debug", boom)
    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})
    assert resp.status_code == 200
    assert any("prompt_debug dump failed" in r.message for r in caplog.records)


def test_chat_turn_end_instrumentation_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "ok", "llm_model": "m", "tokens_used": 1},
    )

    def boom(self, *, output_meta):
        raise RuntimeError("end_turn down")

    monkeypatch.setattr(FakeInstrumentation, "end_turn", boom)
    resp = client.post("/chat", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"})
    assert resp.status_code == 200  # finally guard swallows instrumentation failure
    assert any("turn_end instrumentation failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# /chat/stream additional branches
# ---------------------------------------------------------------------------


def test_chat_stream_fake_assistant_persist_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", False)
    monkeypatch.setattr(
        chat_module,
        "generate_chat_response",
        lambda **kwargs: {"success": True, "response": "abc", "llm_model": "m", "tokens_used": 1},
    )

    def boom(self, *a, **k):
        raise RuntimeError("persist down")

    monkeypatch.setattr(FakePipeline, "persist_assistant", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert "abc" in resp.text
    assert any("fake_stream assistant persist failed" in r.message for r in caplog.records)


def test_chat_stream_fake_generate_failure_yields_error(client, chat_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "streaming_enabled", False)

    def boom(**kwargs):
        raise RuntimeError("generation exploded")

    monkeypatch.setattr(chat_module, "generate_chat_response", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert "[error]" in resp.text


class _UsageWithExtra:
    def __init__(self):
        self.prompt_tokens_reported = 1
        self.completion_tokens_reported = 1
        self.total_tokens_reported = 2
        self.usage_is_estimate = False
        self.extra_usage = {"reasoning_tokens": 3}


class _StreamClientWithExtraUsage:
    def stream_chat(self, *, messages, model, temperature, max_completion_tokens):
        yield ("hi", None)
        yield (None, _UsageWithExtra())


def test_chat_stream_records_extra_usage(client, chat_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _StreamClientWithExtraUsage())
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert "hi" in resp.text


class _StreamClientNoTokens:
    def stream_chat(self, *, messages, model, temperature, max_completion_tokens):
        yield (None, _FakeUsage())  # only usage, never a text token


def test_chat_stream_no_first_token_warns(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _StreamClientNoTokens())
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert any("no first token timing" in r.message for r in caplog.records)


def test_chat_stream_invocation_finalize_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _FakeStreamClient())

    def boom(self, invocation_id, *, usage=None, timing=None):
        raise RuntimeError("end_invocation down")

    monkeypatch.setattr(FakeInstrumentation, "end_invocation", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert any(
        "invocation instrumentation finalization failed" in r.message for r in caplog.records
    )


def test_chat_stream_assistant_persist_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _FakeStreamClient())

    def boom(self, *a, **k):
        raise RuntimeError("persist down")

    monkeypatch.setattr(FakePipeline, "persist_assistant", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert any("stream assistant persist failed" in r.message for r in caplog.records)


def test_chat_stream_turn_end_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _FakeStreamClient())

    def boom(self, *, output_meta):
        raise RuntimeError("end_turn down")

    monkeypatch.setattr(FakeInstrumentation, "end_turn", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert any("stream turn_end failed" in r.message for r in caplog.records)


def test_chat_stream_prompt_debug_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: _FakeStreamClient())

    def boom(**kwargs):
        raise RuntimeError("debug write failed")

    monkeypatch.setattr(chat_module, "dump_prompt_debug", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 200
    assert any("stream prompt_debug dump failed" in r.message for r in caplog.records)


def test_chat_stream_setup_failure_returns_500(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)

    def boom(*a, **k):
        raise RuntimeError("prepare exploded")

    monkeypatch.setattr(chat_module, "_prepare_prompts", boom)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 500
    assert "prepare exploded" in resp.json()["error"]


def test_chat_stream_setup_failure_turn_end_failure_logged(client, chat_env, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "streaming_enabled", True)

    def boom(*a, **k):
        raise RuntimeError("prepare exploded")

    monkeypatch.setattr(chat_module, "_prepare_prompts", boom)

    def boom_end(self, *, output_meta):
        raise RuntimeError("end_turn down")

    monkeypatch.setattr(FakeInstrumentation, "end_turn", boom_end)
    resp = client.post(
        "/chat/stream", json={"message": "hi", "project_id": "p1", "conversation_id": "c1"}
    )
    assert resp.status_code == 500
    assert any("error turn_end failed" in r.message for r in caplog.records)


def test_chat_health_exception_returns_503(client, monkeypatch):
    def boom():
        raise RuntimeError("health down")

    monkeypatch.setattr(chat_module, "get_llm_health", boom)
    resp = client.get("/chat/health")
    assert resp.status_code == 503
    assert "health down" in resp.json()["error"]


def test_chat_stats_failure_returns_500(client, monkeypatch):
    class _BadMM:
        def get_memory_stats(self):
            raise RuntimeError("stats down")

    monkeypatch.setattr(chat_module, "get_memory_manager", lambda: _BadMM())
    resp = client.get("/chat/stats")
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to retrieve statistics"
