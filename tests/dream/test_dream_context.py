"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.context (the Dream Context Block builder).

File sources are written under a temp memory root; the RAG, LLM, and debug-write
boundaries are faked so nothing reaches FAISS, a model, the network, or the real
memory tree.
"""

import os
from types import SimpleNamespace

import pytest
from app.dream import context as ctx


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Point settings at a temp memory root and neutralize debug writers."""
    monkeypatch.setattr(
        ctx,
        "get_settings",
        lambda: SimpleNamespace(
            memory_root=str(tmp_path),
            dream_max_tokens=128,
            dream_model="dream-mini",
            dream_temperature=0.7,
        ),
    )
    monkeypatch.setattr(ctx, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(ctx, "write_dream_context_summary_debug", lambda **k: None)
    monkeypatch.setattr(ctx, "write_dream_prompt_to_execute", lambda **k: None)
    monkeypatch.setattr(ctx, "write_dream_response_usage_debug", lambda **k: None)
    ctx._CONTEXT_CACHE.clear()
    return tmp_path


def _proj_dir(tmp_path, project_id="p1"):
    d = os.path.join(str(tmp_path), project_id)
    os.makedirs(d, exist_ok=True)
    return d


# --- small helpers ---------------------------------------------------------


def test_count_tokens_handles_none():
    assert ctx._count_tokens(None) == 0
    assert ctx._count_tokens("a b c") > 0


def test_read_file_safe_missing_returns_empty(tmp_path):
    assert ctx._read_file_safe(os.path.join(str(tmp_path), "nope.txt")) == ""


def test_read_file_safe_reads(tmp_path):
    p = os.path.join(str(tmp_path), "f.txt")
    with open(p, "w", encoding="utf-8") as h:
        h.write("hello")
    assert ctx._read_file_safe(p) == "hello"


def test_read_file_safe_oserror(tmp_path, monkeypatch, caplog):
    p = os.path.join(str(tmp_path), "f.txt")
    with open(p, "w", encoding="utf-8") as h:
        h.write("x")
    monkeypatch.setattr(ctx.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("io")))
    assert ctx._read_file_safe(p) == ""
    assert any("Failed reading file" in r.message for r in caplog.records)


def test_strip_open_questions_with_end_tag():
    text = "Body\n[Open Questions]\nsome json\n=== END DAILY MEMORY ===\ntail"
    out = ctx._strip_open_questions_section(text)
    assert "[Open Questions]" not in out and "END DAILY MEMORY" in out and "Body" in out


def test_strip_open_questions_without_end_tag():
    text = "Body\n[Open Questions]\nsome json blob"
    out = ctx._strip_open_questions_section(text)
    assert out == "Body"


def test_strip_open_questions_no_marker():
    assert ctx._strip_open_questions_section("plain body") == "plain body"


# --- _get_user_profile -----------------------------------------------------


def test_get_user_profile_prefers_summary(tmp_path, monkeypatch):
    d = _proj_dir(tmp_path)
    with open(os.path.join(d, "user_profile_summary.txt"), "w", encoding="utf-8") as h:
        h.write("profile summary")
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": "RAG"})
    assert ctx._get_user_profile("p1") == "profile summary"


def test_get_user_profile_rag_fallback(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": "rag profile"})
    assert ctx._get_user_profile("p1") == "rag profile"


def test_get_user_profile_file_fallback(tmp_path, monkeypatch, caplog):
    d = _proj_dir(tmp_path)
    with open(os.path.join(d, "default_profile.txt"), "w", encoding="utf-8") as h:
        h.write("default profile")
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": ""})
    assert ctx._get_user_profile("p1") == "default profile"
    assert any("Using fallback file" in r.message for r in caplog.records)


def test_get_user_profile_empty(tmp_path, monkeypatch, caplog):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": ""})
    assert ctx._get_user_profile("p1") == "(empty)"
    assert any("fallback file not found" in r.message for r in caplog.records)


# --- _get_project_system_prompt -------------------------------------------


def test_get_system_prompt_from_rag(monkeypatch):
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": "system rules"})
    assert ctx._get_project_system_prompt("p1") == "system rules"


def test_get_system_prompt_file_fallback(tmp_path, monkeypatch):
    d = _proj_dir(tmp_path)
    with open(os.path.join(d, "system_prompt.txt"), "w", encoding="utf-8") as h:
        h.write("file rules")
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": ""})
    assert ctx._get_project_system_prompt("p1") == "file rules"


def test_get_system_prompt_empty(tmp_path, monkeypatch, caplog):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "retrieve_dream_context", lambda **k: {"context_text": ""})
    assert ctx._get_project_system_prompt("p1") == "(empty)"
    assert any("system rules missing" in r.message for r in caplog.records)


# --- _get_project_context_summary -----------------------------------------


def test_get_context_summary_happy(tmp_path, monkeypatch):
    d = _proj_dir(tmp_path)
    with open(os.path.join(d, "sleep_summary.md"), "w", encoding="utf-8") as h:
        h.write("sleep summary source")
    summary_writes = []
    monkeypatch.setattr(
        ctx,
        "write_dream_context_summary_debug",
        lambda **kwargs: summary_writes.append(kwargs),
    )
    monkeypatch.setattr(
        ctx,
        "generate_text_response",
        lambda *a, **k: SimpleNamespace(text="GEN", usage=SimpleNamespace()),
    )
    assert ctx._get_project_context_summary("p1") == "GEN"
    assert summary_writes == [
        {
            "project_id": "p1",
            "summary_prompt": ctx.build_project_summary_prompt("sleep summary source"),
        }
    ]


def test_get_context_summary_llm_failure(tmp_path, monkeypatch, caplog):
    _proj_dir(tmp_path)
    monkeypatch.setattr(
        ctx, "generate_text_response", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("llm"))
    )
    out = ctx._get_project_context_summary("p1")
    assert "failed to generate" in out
    assert any("LLM call failed" in r.message for r in caplog.records)


def test_get_context_summary_empty_result(tmp_path, monkeypatch, caplog):
    _proj_dir(tmp_path)
    monkeypatch.setattr(
        ctx,
        "generate_text_response",
        lambda *a, **k: SimpleNamespace(text="   ", usage=SimpleNamespace()),
    )
    assert ctx._get_project_context_summary("p1") == "(empty)"
    assert any("Project summary empty" in r.message for r in caplog.records)


# --- _format_question_answers ---------------------------------------------


def test_format_question_answers_non_dict():
    assert ctx._format_question_answers("nope") == "(empty)"


def test_format_question_answers_empty_list():
    assert ctx._format_question_answers({"questions": []}) == "(empty)"


def test_format_question_answers_renders():
    data = {
        "questions": [
            "not-a-dict",
            {"question": "", "answer": ""},  # both empty -> skipped
            {"question": "Q1?", "topic": "t", "answer": "A1"},
        ]
    }
    out = ctx._format_question_answers(data)
    # enumerate counts skipped entries, so the rendered question is Q3.
    assert "Q3: Q1?" in out and "Topic: t" in out and "A1" in out


def test_format_question_answers_all_skipped_returns_empty():
    data = {"questions": [{"question": "", "answer": ""}]}
    assert ctx._format_question_answers(data) == "(empty)"


# --- _get_daily_memory -----------------------------------------------------


def test_get_daily_memory_missing(tmp_path, caplog):
    _proj_dir(tmp_path)
    assert ctx._get_daily_memory("p1") == "(empty)"
    assert any("sleep_summary.md missing" in r.message for r in caplog.records)


def test_get_daily_memory_strips_open_questions(tmp_path):
    d = _proj_dir(tmp_path)
    with open(os.path.join(d, "sleep_summary.md"), "w", encoding="utf-8") as h:
        h.write("Daily body\n[Open Questions]\nblob")
    out = ctx._get_daily_memory("p1")
    assert "Daily body" in out and "[Open Questions]" not in out


# --- _extract_rag_topics ---------------------------------------------------


def test_extract_rag_topics_missing(tmp_path):
    _proj_dir(tmp_path)
    assert ctx._extract_rag_topics("p1") == []


def test_extract_rag_topics_parses_sections(tmp_path):
    d = _proj_dir(tmp_path)
    body = (
        "=== TOPIC: Memory Pipeline ===\n"
        "\n"  # blank line before #topics exercises the skip-blank scan branch
        "#topics: faiss, pruning, faiss\n"
        "content\n"
        "=== TOPIC: Memory Pipeline ===\n"  # duplicate title
        "no topics line here\n"
    )
    with open(os.path.join(d, "sleep_summary.md"), "w", encoding="utf-8") as h:
        h.write(body)
    topics = ctx._extract_rag_topics("p1")
    assert "Memory Pipeline" in topics and "faiss" in topics and "pruning" in topics
    assert topics.count("faiss") == 1  # deduped


# --- _build_project_rag_context -------------------------------------------


def test_build_project_rag_context_no_topics(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "_extract_rag_topics", lambda pid: [])
    out = ctx._build_project_rag_context("p1")
    assert out.strip() == "=== PROJECT RAG CONTEXT ==="


def test_build_project_rag_context_with_hits(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "_extract_rag_topics", lambda pid: ["t1"])
    monkeypatch.setattr(
        ctx, "retrieve_dream_context", lambda **k: {"context_text": "hit text", "total_hits": 3}
    )
    out = ctx._build_project_rag_context("p1")
    assert "Topic Query: t1" in out and "hit text" in out


def test_build_project_rag_context_retrieval_error_and_empty(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "_extract_rag_topics", lambda pid: ["bad", "empty"])

    def _retrieve(**k):
        if k["query"] == "bad":
            raise RuntimeError("retrieval boom")
        return {"context_text": ""}  # empty -> skipped

    monkeypatch.setattr(ctx, "retrieve_dream_context", _retrieve)
    out = ctx._build_project_rag_context("p1")
    assert "No relevant long-term memory" in out


# --- build_dream_context ---------------------------------------------------


def test_build_dream_context_happy(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(ctx, "_get_user_profile", lambda pid: "UP")
    monkeypatch.setattr(ctx, "_get_project_system_prompt", lambda pid: "SP")
    monkeypatch.setattr(ctx, "_get_project_context_summary", lambda pid: "CS")
    monkeypatch.setattr(ctx, "_get_daily_memory", lambda pid: "DM")
    monkeypatch.setattr(
        ctx, "_build_project_rag_context", lambda pid: "=== PROJECT RAG CONTEXT ===\n"
    )
    block, summary = ctx.build_dream_context("p1", {"questions": []})
    assert "=== USER PROFILE ===" in block and "UP" in block and "CS" in block
    assert summary == "CS"


def test_build_dream_context_fallback_on_failure(tmp_path, monkeypatch):
    _proj_dir(tmp_path)
    monkeypatch.setattr(
        ctx, "_get_user_profile", lambda pid: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(ctx, "_get_daily_memory", lambda pid: "DM-fallback")
    block, summary = ctx.build_dream_context("p1", {"questions": []})
    assert "=== DAILY MEMORY ===" in block and "DM-fallback" in block
    assert summary == "(empty)"


def test_build_dream_context_fallback_daily_also_fails(tmp_path, monkeypatch, caplog):
    _proj_dir(tmp_path)
    monkeypatch.setattr(
        ctx, "_get_user_profile", lambda pid: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        ctx, "_get_daily_memory", lambda pid: (_ for _ in ()).throw(RuntimeError("daily boom"))
    )
    block, summary = ctx.build_dream_context("p1", {"questions": []})
    assert "(empty)" in block and summary == "(empty)"
    assert any("fallback failed loading daily memory" in r.message for r in caplog.records)
