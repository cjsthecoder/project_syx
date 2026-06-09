"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.rag (the dream retrieval adapter).

The daily flag check uses the real temp DB via the ``db`` fixture; the
route-policy/merge boundary is faked so retrieval never touches FAISS,
embeddings, or the network.
"""

from types import SimpleNamespace

from app.dream import rag as dream_rag


def test_empty_result_shape():
    out = dream_rag._empty_result(route="OTHER", per_source_k=2, max_keep=3, daily_enabled=True)
    assert out["route"] == "OTHER"
    assert out["context_text"] == "" and out["total_hits"] == 0
    assert out["per_source_k"] == 2 and out["max_keep"] == 3 and out["daily_enabled"] is True


def test_daily_enabled_reads_flag(db):
    from app.core.db_models import Project
    from sqlmodel import Session

    with Session(db) as session:
        session.add(
            Project(id="pDaily", name="x", description="x", system=False, daily_rag_enabled=False)
        )
        session.commit()
    assert dream_rag._daily_enabled("pDaily") is False


def test_daily_enabled_missing_project_defaults_true(db):
    assert dream_rag._daily_enabled("missing") is True


def test_daily_enabled_defaults_true_on_error(monkeypatch):
    monkeypatch.setattr(
        dream_rag, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    assert dream_rag._daily_enabled("p") is True


def test_retrieve_dream_context_happy(monkeypatch):
    monkeypatch.setattr(dream_rag, "get_settings", lambda: SimpleNamespace(base_top_k=4))
    monkeypatch.setattr(
        dream_rag,
        "get_route_policy",
        lambda r: SimpleNamespace(retrieval_multiplier=1.0, max_keep=5),
    )
    monkeypatch.setattr(dream_rag, "_daily_enabled", lambda pid: True)
    monkeypatch.setattr(
        dream_rag,
        "merge_daily_and_main",
        lambda **k: {"context_text": "ctx", "total_hits": 2},
    )
    out = dream_rag.retrieve_dream_context(project_id="p1", query="q", route="exploratory")
    assert out["context_text"] == "ctx"
    assert out["route"] == "EXPLORATORY" and out["per_source_k"] == 4 and out["max_keep"] == 5
    assert out["daily_enabled"] is True


def test_retrieve_dream_context_empty_when_no_budget(monkeypatch):
    monkeypatch.setattr(dream_rag, "get_settings", lambda: SimpleNamespace(base_top_k=4))
    monkeypatch.setattr(
        dream_rag,
        "get_route_policy",
        lambda r: SimpleNamespace(retrieval_multiplier=0.0, max_keep=5),
    )
    monkeypatch.setattr(dream_rag, "_daily_enabled", lambda pid: True)
    out = dream_rag.retrieve_dream_context(project_id="p1", query="q", route="DIRECT")
    assert out["context_text"] == "" and out["per_source_k"] == 0


def test_retrieve_dream_context_blank_route_resolves_other(monkeypatch):
    monkeypatch.setattr(dream_rag, "get_settings", lambda: SimpleNamespace(base_top_k=4))
    monkeypatch.setattr(
        dream_rag,
        "get_route_policy",
        lambda r: SimpleNamespace(retrieval_multiplier=0.0, max_keep=0),
    )
    monkeypatch.setattr(dream_rag, "_daily_enabled", lambda pid: True)
    out = dream_rag.retrieve_dream_context(project_id="p1", query="q", route="")
    assert out["route"] == "OTHER"


def test_retrieve_dream_context_empty_on_failure(monkeypatch):
    monkeypatch.setattr(dream_rag, "get_settings", lambda: SimpleNamespace(base_top_k=4))
    monkeypatch.setattr(
        dream_rag,
        "get_route_policy",
        lambda r: SimpleNamespace(retrieval_multiplier=1.0, max_keep=5),
    )
    monkeypatch.setattr(dream_rag, "_daily_enabled", lambda pid: True)
    monkeypatch.setattr(
        dream_rag,
        "merge_daily_and_main",
        lambda **k: (_ for _ in ()).throw(RuntimeError("merge boom")),
    )
    out = dream_rag.retrieve_dream_context(project_id="p1", query="q", route="SYNTHESIS")
    assert out["context_text"] == "" and out["route"] == "SYNTHESIS"
