"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.api.chat_pipeline.ChatPipeline.

The pipeline owns the non-LLM chat orchestration helpers (history/prompt load,
route classification, RAG context assembly, message building, persistence). Each
method is exercised directly with its boundaries faked: get_memory_manager,
get_session, build_query, get_route_policy, merge_daily_and_main,
get_instrumentation, and write_debug_file. No TestClient and no real LLM.
"""

from types import SimpleNamespace

import app.api.chat_pipeline as cp
import pytest
from fastapi import HTTPException


def _settings(**overrides):
    base = dict(
        rag_on_chat=True,
        base_top_k=5,
        log_preview_max_chars=80,
        available_models=["gpt-test", "gpt-mini"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _pipeline(**overrides):
    return cp.ChatPipeline(_settings(**overrides))


class _FakeSession:
    """Context-manager session whose get() returns a preset object."""

    def __init__(self, obj=None, raise_exc=None):
        self._obj = obj
        self._raise = raise_exc

    def get(self, _model, _pk):
        if self._raise is not None:
            raise self._raise
        return self._obj

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


# --- build_conversation_history -------------------------------------------


def test_build_conversation_history_no_project_returns_none():
    assert _pipeline().build_conversation_history(None) is None


def test_build_conversation_history_maps_messages(monkeypatch):
    mm = SimpleNamespace(
        get_project_history=lambda pid: [
            {
                "role": "user",
                "content": "hi",
                "tags_meta_json": None,
                "semantic_handle": None,
                "namespace": "other",
                "keep": False,
            }
        ]
    )
    monkeypatch.setattr(cp, "get_memory_manager", lambda: mm)
    out = _pipeline().build_conversation_history("p1")
    assert out == [
        {
            "role": "user",
            "content": "hi",
            "tags_meta_json": None,
            "semantic_handle": None,
            "namespace": "other",
            "keep": False,
        }
    ]


def test_build_conversation_history_failure_returns_none(monkeypatch, caplog):
    def boom():
        raise TypeError("mm unavailable")

    monkeypatch.setattr(cp, "get_memory_manager", boom)
    assert _pipeline().build_conversation_history("p1") is None
    assert any("history load failed" in r.message for r in caplog.records)


# --- load_project_prompts -------------------------------------------------


def test_load_project_prompts_no_project():
    assert _pipeline().load_project_prompts(None) == (None, None, None)


def test_load_project_prompts_happy(monkeypatch):
    monkeypatch.setattr(cp, "load_project_system_prompt", lambda pid: "SYS")
    monkeypatch.setattr(
        cp,
        "load_project_personality",
        lambda pid: {
            "creativity": 0.5,
            "tone": "warm",
            "verbosity": "verbose",
            "format": "text",
            "domain_focus": ["ml"],
        },
    )
    base, hint, creativity = _pipeline().load_project_prompts("p1")
    assert base == "SYS"
    assert creativity == 0.5
    assert "tone=warm" in hint and "domain_focus=['ml']" in hint


def test_load_project_prompts_non_list_domains_coerced(monkeypatch):
    monkeypatch.setattr(cp, "load_project_system_prompt", lambda pid: "SYS")
    monkeypatch.setattr(
        cp,
        "load_project_personality",
        lambda pid: {"creativity": None, "domain_focus": "not-a-list"},
    )
    base, hint, creativity = _pipeline().load_project_prompts("p1")
    assert creativity == 0.0  # None creativity -> 0.0
    assert "domain_focus=[]" in hint  # non-list coerced to empty list


def test_load_project_prompts_failure_returns_none(monkeypatch, caplog):
    def boom(_pid):
        raise KeyError("missing")

    monkeypatch.setattr(cp, "load_project_system_prompt", boom)
    assert _pipeline().load_project_prompts("p1") == (None, None, None)
    assert any("prompt load failed" in r.message for r in caplog.records)


# --- _build_builder_summary / helpers -------------------------------------


def test_latest_assistant_tags_meta_finds_newest():
    p = _pipeline()
    history = [
        {"role": "assistant", "tags_meta_json": '{"old": 1}'},
        {"role": "user", "content": "q"},
        {"role": "assistant", "tags_meta_json": '{"new": 2}'},
    ]
    assert p._latest_assistant_tags_meta(history) == '{"new": 2}'


def test_latest_assistant_tags_meta_empty_and_none():
    p = _pipeline()
    assert p._latest_assistant_tags_meta(None) == ""
    assert p._latest_assistant_tags_meta([{"role": "user", "content": "q"}]) == ""


def test_project_semantic_handle_summary_no_project():
    assert _pipeline()._project_semantic_handle_summary(None) == ""


def test_project_semantic_handle_summary_returns_json(monkeypatch):
    project = SimpleNamespace(last_semantic_handle="my handle")
    monkeypatch.setattr(cp, "get_session", lambda: _FakeSession(obj=project))
    out = _pipeline()._project_semantic_handle_summary("p1")
    assert '"semantic_handle": "my handle"' in out


def test_project_semantic_handle_summary_no_handle(monkeypatch):
    monkeypatch.setattr(
        cp, "get_session", lambda: _FakeSession(obj=SimpleNamespace(last_semantic_handle=None))
    )
    assert _pipeline()._project_semantic_handle_summary("p1") == ""


def test_project_semantic_handle_summary_lookup_error(monkeypatch, caplog):
    monkeypatch.setattr(cp, "get_session", lambda: _FakeSession(raise_exc=RuntimeError("db down")))
    assert _pipeline()._project_semantic_handle_summary("p1") == ""
    assert any("fallback lookup" in r.message for r in caplog.records)


def test_build_builder_summary_prefers_direct(monkeypatch):
    p = _pipeline()
    history = [{"role": "assistant", "tags_meta_json": '{"x": 1}'}]
    assert p._build_builder_summary("p1", history) == '{"x": 1}'


def test_build_builder_summary_falls_back_to_handle(monkeypatch):
    project = SimpleNamespace(last_semantic_handle="handle")
    monkeypatch.setattr(cp, "get_session", lambda: _FakeSession(obj=project))
    p = _pipeline()
    out = p._build_builder_summary("p1", [{"role": "user", "content": "q"}])
    assert "handle" in out


def test_build_builder_summary_swallows_error(monkeypatch, caplog):
    p = _pipeline()

    def boom(_history):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(p, "_latest_assistant_tags_meta", boom)
    assert p._build_builder_summary("p1", []) == ""
    assert any("builder summary failed" in r.message for r in caplog.records)


# --- previous_pair_text ---------------------------------------------------


def test_previous_pair_text_none_history():
    assert _pipeline().previous_pair_text(None) is None


def test_previous_pair_text_builds_pair():
    history = [
        {"role": "user", "content": "the question"},
        {
            "role": "assistant",
            "content": "the answer",
            "namespace": "Research",
            "keep": True,
            "tags_meta_json": '{"topics": "t", "intent": "i", "type": "q", "semantic_handle": "h"}',
        },
    ]
    out = _pipeline().previous_pair_text(history)
    assert "#route: research" in out
    assert "#keep: true" in out
    assert "#topics: t" in out
    assert "User: the question" in out
    assert "Assistant: the answer" in out


def test_previous_pair_text_no_assistant_returns_none():
    assert _pipeline().previous_pair_text([{"role": "user", "content": "q"}]) is None


def test_previous_pair_text_no_user_before_assistant_returns_none():
    assert _pipeline().previous_pair_text([{"role": "assistant", "content": "a"}]) is None


def test_previous_pair_text_non_dict_element_returns_none(caplog):
    # A non-dict history element makes the scan raise; the outer guard returns None.
    out = _pipeline().previous_pair_text([None, {"role": "assistant", "content": "a"}])
    assert out is None
    assert any("previous_pair_text failed" in r.message for r in caplog.records)


def test_previous_pair_text_bad_tags_json_still_returns(caplog):
    history = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "tags_meta_json": "{not json"},
    ]
    out = _pipeline().previous_pair_text(history)
    assert "User: q" in out
    assert "#topics: \n" in out  # tags left blank when parse fails


# --- _daily_enabled -------------------------------------------------------


def test_daily_enabled_true_and_false(monkeypatch):
    monkeypatch.setattr(
        cp, "get_session", lambda: _FakeSession(obj=SimpleNamespace(daily_rag_enabled=False))
    )
    assert _pipeline()._daily_enabled("p1") is False
    monkeypatch.setattr(
        cp, "get_session", lambda: _FakeSession(obj=SimpleNamespace(daily_rag_enabled=True))
    )
    assert _pipeline()._daily_enabled("p1") is True


def test_daily_enabled_missing_project_defaults_true(monkeypatch):
    monkeypatch.setattr(cp, "get_session", lambda: _FakeSession(obj=None))
    assert _pipeline()._daily_enabled("p1") is True


def test_daily_enabled_lookup_error_defaults_true(monkeypatch):
    monkeypatch.setattr(cp, "get_session", lambda: _FakeSession(raise_exc=OSError("db")))
    assert _pipeline()._daily_enabled("p1") is True


# --- _initial_rag_metrics -------------------------------------------------


def test_initial_rag_metrics_shape():
    m = cp.ChatPipeline._initial_rag_metrics()
    assert m["route"] == "OTHER"
    assert m["rag_enabled"] is False
    assert m["retrieved_count"] == 0


# --- _classify_route ------------------------------------------------------


def test_classify_route_builder_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(cp, "build_query", lambda *a, **k: None)
    out = _pipeline()._classify_route(
        project_id="p1", message="hi", summary="", preview="hi", msg_id="m1"
    )
    assert out is None


def test_classify_route_returns_upper_route(monkeypatch):
    monkeypatch.setattr(
        cp,
        "build_query",
        lambda *a, **k: {"route": "direct", "confidence": 0.9, "topics": ["t"], "standalone": "s"},
    )
    out = _pipeline()._classify_route(
        project_id="p1", message="hi", summary="", preview="hi", msg_id="m1"
    )
    assert out == "DIRECT"


def test_classify_route_default_other_when_route_missing(monkeypatch):
    # No route key -> defaults to OTHER; confidence omitted (None) -> 0.0.
    monkeypatch.setattr(cp, "build_query", lambda *a, **k: {"topics": []})
    out = _pipeline()._classify_route(
        project_id="p1", message="hi", summary="", preview="hi", msg_id="m1"
    )
    assert out == "OTHER"


# --- _resolve_retrieval_policy --------------------------------------------


def test_resolve_retrieval_policy(monkeypatch):
    pol = SimpleNamespace(retrieval_multiplier=2.0, max_keep=4, min_score=0.1)
    monkeypatch.setattr(cp, "get_route_policy", lambda route: pol)
    resolved, per_source_k = _pipeline()._resolve_retrieval_policy("DIRECT")
    assert resolved is pol
    assert isinstance(per_source_k, int)
    assert per_source_k > 0


# --- _write_rag_query_debug -----------------------------------------------


def test_write_rag_query_debug_happy(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cp, "write_debug_file", lambda pid, path, body: captured.update(pid=pid, body=body)
    )
    pol = SimpleNamespace(retrieval_multiplier=1.0, max_keep=3, min_score=0.2)
    _pipeline()._write_rag_query_debug(
        project_id="p1",
        route="DIRECT",
        pol=pol,
        per_source_k=5,
        queries=["q1", ""],
        message="hello",
        primary_query="ctx hello",
        msg_id="m1",
    )
    assert captured["pid"] == "p1"
    assert "route: DIRECT" in captured["body"]
    assert "queries_count: 1" in captured["body"]


def test_write_rag_query_debug_swallows_error(monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("write failed")

    monkeypatch.setattr(cp, "write_debug_file", boom)
    pol = SimpleNamespace(retrieval_multiplier=1.0, max_keep=3, min_score=0.2)
    # Must not raise.
    _pipeline()._write_rag_query_debug(
        project_id="p1",
        route="DIRECT",
        pol=pol,
        per_source_k=5,
        queries=["q"],
        message="m",
        primary_query="pq",
        msg_id="m1",
    )


# --- compute_rag_context --------------------------------------------------


def test_compute_rag_context_disabled_returns_none():
    p = _pipeline(rag_on_chat=False)
    out = p.compute_rag_context(
        project_id="p1", message="hi", preview="hi", msg_id="m1", conversation_history=None
    )
    assert out[0] is None and out[1] is None
    assert out[2]["rag_enabled"] is False


def test_compute_rag_context_no_project_returns_none():
    out = _pipeline().compute_rag_context(
        project_id=None, message="hi", preview="hi", msg_id="m1", conversation_history=None
    )
    assert out[0] is None and out[1] is None


def test_compute_rag_context_route_none_returns_none(monkeypatch):
    monkeypatch.setattr(cp, "build_query", lambda *a, **k: None)
    out = _pipeline().compute_rag_context(
        project_id="p1", message="hi", preview="hi", msg_id="m1", conversation_history=None
    )
    assert out[0] is None and out[1] is None


def test_compute_rag_context_per_source_k_zero_skips(monkeypatch):
    monkeypatch.setattr(cp, "build_query", lambda *a, **k: {"route": "direct"})
    monkeypatch.setattr(cp, "set_route", lambda r: None)
    monkeypatch.setattr(cp, "set_namespace", lambda n: None)
    monkeypatch.setattr(
        cp,
        "get_route_policy",
        lambda route: SimpleNamespace(retrieval_multiplier=0.0, max_keep=3, min_score=0.2),
    )
    monkeypatch.setattr(cp, "compute_per_source_k", lambda base, mult: 0)
    out = _pipeline().compute_rag_context(
        project_id="p1", message="hi", preview="hi", msg_id="m1", conversation_history=None
    )
    assert out[0] is None
    assert out[1] == "direct"  # namespace still set


def test_compute_rag_context_happy(monkeypatch):
    monkeypatch.setattr(cp, "build_query", lambda *a, **k: {"route": "direct"})
    monkeypatch.setattr(cp, "set_route", lambda r: None)
    monkeypatch.setattr(cp, "set_namespace", lambda n: None)
    monkeypatch.setattr(
        cp,
        "get_route_policy",
        lambda route: SimpleNamespace(retrieval_multiplier=1.0, max_keep=3, min_score=0.2),
    )
    monkeypatch.setattr(cp, "compute_per_source_k", lambda base, mult: 5)
    monkeypatch.setattr(cp, "format_contextual_turn", lambda m, s: f"CTX:{m}")
    monkeypatch.setattr(cp, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(
        cp,
        "merge_daily_and_main",
        lambda **kwargs: {
            "context_text": "CONTEXT",
            "ordered_candidates": 7,
            "selected_candidates": 3,
            "expanded_unique_chunks_after_merge": 2,
            "tokens_used": 99,
        },
    )
    monkeypatch.setattr(
        cp, "get_session", lambda: _FakeSession(obj=SimpleNamespace(daily_rag_enabled=True))
    )
    prompt, ns, metrics = _pipeline().compute_rag_context(
        project_id="p1", message="hi", preview="hi", msg_id="m1", conversation_history=None
    )
    assert prompt == "CONTEXT"
    assert ns == "direct"
    assert metrics["rag_enabled"] is True
    assert metrics["retrieved_count"] == 7
    assert metrics["kept_count"] == 3
    assert metrics["rag_tokens_injected_est"] == 99


# --- apply_rag_guidance ---------------------------------------------------


def test_apply_rag_guidance_no_rag_returns_base():
    assert _pipeline().apply_rag_guidance("BASE", None) == "BASE"


def test_apply_rag_guidance_appends_to_base():
    out = _pipeline().apply_rag_guidance("BASE", "RAG")
    assert out.startswith("BASE")
    assert cp.RAG_SYSTEM_PROMPT.strip() in out


def test_apply_rag_guidance_no_base_returns_guidance_only():
    out = _pipeline().apply_rag_guidance(None, "RAG")
    assert out.startswith(cp.RAG_SYSTEM_PROMPT.strip())


def test_apply_rag_guidance_handles_bad_base_type(caplog):
    # A non-string base prompt triggers the AttributeError guard.
    out = _pipeline().apply_rag_guidance(123, "RAG")  # type: ignore[arg-type]
    assert out == 123
    assert any("apply_rag_guidance failed" in r.message for r in caplog.records)


# --- enforce_model_whitelist ----------------------------------------------


def test_enforce_model_whitelist_none_allowed():
    _pipeline().enforce_model_whitelist(None)  # no raise


def test_enforce_model_whitelist_allowed():
    _pipeline().enforce_model_whitelist("gpt-test")  # no raise


def test_enforce_model_whitelist_rejected():
    with pytest.raises(HTTPException) as exc:
        _pipeline().enforce_model_whitelist("forbidden-model")
    assert exc.value.status_code == 400


# --- build_llm_messages ---------------------------------------------------


def test_build_llm_messages_orders_sections(monkeypatch):
    monkeypatch.setattr(
        cp, "get_instrumentation", lambda: SimpleNamespace(record_stage=lambda *a, **k: None)
    )
    msgs = _pipeline().build_llm_messages(
        base_system_prompt="SYS",
        assistant_hint="HINT",
        rag_system_prompt="RAG",
        conversation_history=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ],
        user_message="now",
    )
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "assistant", "system", "user", "assistant", "user"]
    assert msgs[0]["content"] == "SYS"
    assert msgs[-1]["content"] == "now"


def test_build_llm_messages_minimal(monkeypatch):
    monkeypatch.setattr(
        cp, "get_instrumentation", lambda: SimpleNamespace(record_stage=lambda *a, **k: None)
    )
    msgs = _pipeline().build_llm_messages(
        base_system_prompt=None,
        assistant_hint=None,
        rag_system_prompt=None,
        conversation_history=None,
        user_message="hi",
    )
    assert msgs == [{"role": "user", "content": "hi"}]


def test_build_llm_messages_instrumentation_failure_logged(monkeypatch, caplog):
    def boom():
        raise RuntimeError("instr down")

    monkeypatch.setattr(cp, "get_instrumentation", boom)
    msgs = _pipeline().build_llm_messages(
        base_system_prompt="S",
        assistant_hint=None,
        rag_system_prompt=None,
        conversation_history=None,
        user_message="hi",
    )
    assert msgs[-1]["content"] == "hi"  # still assembled
    assert any("prompt_assembly instrumentation failed" in r.message for r in caplog.records)


# --- persist_user / persist_assistant -------------------------------------


def test_persist_user_no_project_noop(monkeypatch):
    called = []
    monkeypatch.setattr(cp, "get_memory_manager", lambda: called.append(1))
    _pipeline().persist_user(None, "msg")
    assert called == []


def test_persist_user_happy(monkeypatch):
    calls = []
    mm = SimpleNamespace(append_user_message=lambda pid, msg: calls.append((pid, msg)))
    monkeypatch.setattr(cp, "get_memory_manager", lambda: mm)
    _pipeline().persist_user("p1", "hello")
    assert calls == [("p1", "hello")]


def test_persist_user_failure_logged(monkeypatch, caplog):
    def boom():
        raise RuntimeError("mm down")

    monkeypatch.setattr(cp, "get_memory_manager", boom)
    _pipeline().persist_user("p1", "hello")  # no raise
    assert any("persist_user failed" in r.message for r in caplog.records)


def test_persist_assistant_no_project_noop(monkeypatch):
    called = []
    monkeypatch.setattr(cp, "get_memory_manager", lambda: called.append(1))
    _pipeline().persist_assistant(None, "msg", "other")
    assert called == []


def test_persist_assistant_happy(monkeypatch):
    calls = []

    def append_assistant_message(pid, msg, *, namespace, **kwargs):
        calls.append((pid, msg, namespace, kwargs))

    mm = SimpleNamespace(append_assistant_message=append_assistant_message)
    monkeypatch.setattr(cp, "get_memory_manager", lambda: mm)
    _pipeline().persist_assistant(
        "p1", "answer", "research", user_text_for_tagging="u", forget=False
    )
    assert calls[0][0] == "p1"
    assert calls[0][2] == "research"


def test_persist_assistant_chitchat_logs(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    mm = SimpleNamespace(append_assistant_message=lambda *a, **k: None)
    monkeypatch.setattr(cp, "get_memory_manager", lambda: mm)
    _pipeline().persist_assistant("p1", "ok", "chitchat", forget=True, skip_tagger=True)
    assert any("CHITCHAT" in r.message for r in caplog.records)


def test_persist_assistant_failure_logged(monkeypatch, caplog):
    def boom():
        raise RuntimeError("mm down")

    monkeypatch.setattr(cp, "get_memory_manager", boom)
    _pipeline().persist_assistant("p1", "ok", "other")  # no raise
    assert any("persist_assistant failed" in r.message for r in caplog.records)
