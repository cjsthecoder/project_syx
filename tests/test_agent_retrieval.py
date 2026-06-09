"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.agent_interface.retrieval and the response model serializer.

Fakes only the boundaries (get_session, merge_daily_and_main, the parser, the
entry expander, the route policy, and write_debug_file) so the retrieval
orchestration, debug-artifact writer, and diagnostics summary are exercised
without touching FAISS, embeddings, or the network.
"""

import uuid
from types import SimpleNamespace

import pytest
from app.agent_interface import retrieval as R
from app.agent_interface.models import AgentMemorySearchResponse, AgentMemorySnippet
from app.agent_interface.parser import SnippetParseError
from app.core.db_models import Project
from sqlmodel import Session


def _snippet(num, *, mode="bounded_entry", memory_id=None):
    return AgentMemorySnippet(snippet_number=num, result_mode=mode, memory_id=memory_id, text="t")


class _FakeSession:
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


def _make_project(engine, name):
    pid = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Project(id=pid, name=name, description=name, system=False))
        session.commit()
    return pid


# --- resolve_project_name -------------------------------------------------


def test_resolve_project_name_blank_returns_none():
    assert R.resolve_project_name("   ") is None


def test_resolve_project_name_match(db):
    pid = _make_project(db, "Alpha")
    found = R.resolve_project_name("alpha")  # case-insensitive
    assert found is not None and found.id == pid


def test_resolve_project_name_no_match(db):
    _make_project(db, "Alpha")
    assert R.resolve_project_name("Beta") is None


def test_resolve_project_name_duplicate_warns_and_returns_first(db, caplog):
    _make_project(db, "Dup")
    _make_project(db, "Dup")
    found = R.resolve_project_name("dup")
    assert found is not None
    assert any("duplicate project_name match" in r.message for r in caplog.records)


# --- normalize_category ---------------------------------------------------


def test_normalize_category():
    assert R.normalize_category("DIRECT") == "DIRECT"
    assert R.normalize_category("chitchat") == "OTHER"  # chitchat has no retrieval
    assert R.normalize_category("unknown-route") == "OTHER"
    assert R.normalize_category(None) == "OTHER"


# --- retrieve_agent_memory ------------------------------------------------


def _patch_policy(monkeypatch, *, multiplier=1.0, max_keep=3, per_source_k=5):
    monkeypatch.setattr(R, "get_settings", lambda: SimpleNamespace(base_top_k=5))
    monkeypatch.setattr(
        R,
        "get_route_policy",
        lambda route: SimpleNamespace(retrieval_multiplier=multiplier, max_keep=max_keep),
    )
    monkeypatch.setattr(R, "compute_per_source_k", lambda base, mult: per_source_k)


def test_retrieve_agent_memory_no_retrieval_when_k_zero(monkeypatch):
    _patch_policy(monkeypatch, per_source_k=0)
    # merge_daily_and_main must not be called when per_source_k <= 0.
    monkeypatch.setattr(
        R, "merge_daily_and_main", lambda **k: (_ for _ in ()).throw(AssertionError("called"))
    )
    response, raw, warnings = R.retrieve_agent_memory(
        project_name="P", project_id="p1", query="q", category="OTHER", model=None
    )
    assert raw == ""
    assert response.snippet_count == 0
    assert warnings == []


def test_retrieve_agent_memory_no_retrieval_when_max_keep_zero(monkeypatch):
    _patch_policy(monkeypatch, max_keep=0, per_source_k=5)
    monkeypatch.setattr(
        R, "merge_daily_and_main", lambda **k: (_ for _ in ()).throw(AssertionError("called"))
    )
    response, raw, _ = R.retrieve_agent_memory(
        project_name="P", project_id="p1", query="q", category="OTHER", model=None
    )
    assert raw == "" and response.snippet_count == 0


def test_retrieve_agent_memory_happy(monkeypatch):
    _patch_policy(monkeypatch)
    monkeypatch.setattr(R, "_daily_enabled", lambda pid: True)
    monkeypatch.setattr(R, "merge_daily_and_main", lambda **k: {"context_text": "raw ctx"})
    parsed = [_snippet(1, memory_id="m1"), _snippet(2, mode="unbounded_chunk_group")]
    monkeypatch.setattr(R, "parse_prompt_context_to_snippets", lambda raw: parsed)
    monkeypatch.setattr(R, "expand_agent_memory_snippets", lambda *, project_id, snippets: snippets)
    response, raw, _ = R.retrieve_agent_memory(
        project_name="P", project_id="p1", query="q", category="DIRECT", model="gpt-x"
    )
    assert raw == "raw ctx"
    assert response.snippet_count == 2
    assert response.bounded_result_count == 1
    assert response.unbounded_result_count == 1
    assert response.model == "gpt-x"


def test_retrieve_agent_memory_parse_error_reraised_with_context(monkeypatch):
    _patch_policy(monkeypatch)
    monkeypatch.setattr(R, "_daily_enabled", lambda pid: True)
    monkeypatch.setattr(R, "merge_daily_and_main", lambda **k: {"context_text": "raw ctx"})

    def boom(_raw):
        raise SnippetParseError("bad block")

    monkeypatch.setattr(R, "parse_prompt_context_to_snippets", boom)
    with pytest.raises(SnippetParseError) as exc:
        R.retrieve_agent_memory(
            project_name="P", project_id="p1", query="q", category="OTHER", model=None
        )
    assert exc.value.raw_context == "raw ctx"


def test_retrieve_agent_memory_generic_parse_failure_wrapped(monkeypatch):
    _patch_policy(monkeypatch)
    monkeypatch.setattr(R, "_daily_enabled", lambda pid: True)
    monkeypatch.setattr(R, "merge_daily_and_main", lambda **k: {"context_text": "raw ctx"})

    def boom(_raw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(R, "parse_prompt_context_to_snippets", boom)
    with pytest.raises(SnippetParseError) as exc:
        R.retrieve_agent_memory(
            project_name="P", project_id="p1", query="q", category="OTHER", model=None
        )
    assert exc.value.raw_context == "raw ctx"
    assert "unexpected" in str(exc.value)


# --- write_agent_debug_files ----------------------------------------------


def test_write_agent_debug_files_writes_query_and_response(monkeypatch):
    writes = []
    monkeypatch.setattr(R, "write_debug_file", lambda pid, path, body: writes.append((path, body)))
    R.write_agent_debug_files(
        project_id="p1",
        request_payload={"query": "q"},
        raw_context="ctx",
        response_payload={"snippets": []},
        parser_warnings=["w1"],
    )
    assert len(writes) == 2
    paths = [p for p, _ in writes]
    assert any(p.endswith("_agent_query.txt") for p in paths)
    assert any(p.endswith("_agent_response.txt") for p in paths)


# --- _build_response ------------------------------------------------------


def test_build_response_counts():
    snippets = [
        _snippet(1, memory_id="m1"),
        _snippet(2, mode="unbounded_chunk_group"),
        _snippet(3, memory_id="m3"),
    ]
    resp = R._build_response(
        project_name="P",
        project_id="p1",
        query="q",
        category="OTHER",
        model=None,
        snippets=snippets,
    )
    assert resp.bounded_result_count == 2
    assert resp.unbounded_result_count == 1
    assert resp.snippet_count == 3


# --- _daily_enabled -------------------------------------------------------


def test_daily_enabled_true_false(monkeypatch):
    monkeypatch.setattr(
        R, "get_session", lambda: _FakeSession(obj=SimpleNamespace(daily_rag_enabled=False))
    )
    assert R._daily_enabled("p1") is False
    monkeypatch.setattr(
        R, "get_session", lambda: _FakeSession(obj=SimpleNamespace(daily_rag_enabled=True))
    )
    assert R._daily_enabled("p1") is True


def test_daily_enabled_missing_defaults_true(monkeypatch):
    monkeypatch.setattr(R, "get_session", lambda: _FakeSession(obj=None))
    assert R._daily_enabled("p1") is True


def test_daily_enabled_lookup_error_defaults_true(monkeypatch, caplog):
    monkeypatch.setattr(R, "get_session", lambda: _FakeSession(raise_exc=RuntimeError("db down")))
    assert R._daily_enabled("p1") is True
    assert any("daily flag lookup failed" in r.message for r in caplog.records)


# --- _entry_expansion_summary ---------------------------------------------


def test_entry_expansion_summary_non_list_snippets():
    out = R._entry_expansion_summary({"snippets": "not a list"})
    assert out["bounded_snippets"] == 0
    assert out["memory_ids"] == []


def test_entry_expansion_summary_aggregates():
    payload = {
        "snippets": [
            "not-a-dict",  # skipped
            {
                "result_mode": "bounded_entry",
                "entry_expansion_status": "expanded",
                "entry_expansion_method": "artifact_path_boundary",
                "entry_expansion_truncated": True,
                "memory_id": "m1",
            },
            {
                "result_mode": "bounded_entry",
                "entry_expansion_status": "fallback",
                "entry_expansion_method": "docstore_reconstruction",
                "memory_id": "  ",  # blank -> not collected
            },
            {"result_mode": "unbounded_chunk_group"},  # status/method default to "missing"
        ]
    }
    out = R._entry_expansion_summary(payload)
    assert out["bounded_snippets"] == 2
    assert out["expanded"] == 1
    assert out["fallback"] == 1
    assert out["truncated"] == 1
    assert out["memory_ids"] == ["m1"]
    assert out["statuses"]["missing"] == 1


# --- AgentMemorySearchResponse.to_response_dict ---------------------------


def test_to_response_dict_drops_model_when_none():
    resp = AgentMemorySearchResponse(
        project_name="P", project_id="p1", category="OTHER", query="q", model=None
    )
    data = resp.to_response_dict()
    assert "model" not in data


def test_to_response_dict_keeps_model_when_set():
    resp = AgentMemorySearchResponse(
        project_name="P", project_id="p1", category="OTHER", query="q", model="gpt-x"
    )
    assert resp.to_response_dict()["model"] == "gpt-x"
