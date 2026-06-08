"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Contract tests for the projects API router.

A minimal FastAPI app mounts only the projects router against an isolated temp
SQLite engine and memory root. The FAISS rebuild is patched to a no-op so create
flows never reach embeddings/network.
"""

import itertools
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api import projects as projects_module
from app.core.db_models import Project


@pytest.fixture
def client(db, temp_memory_root, reset_projects_state, monkeypatch):
    monkeypatch.setattr(projects_module, "rebuild_faiss_index", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(projects_module.router)
    return TestClient(app)


def _make_project(engine, *, name, system=False):
    import uuid

    pid = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Project(id=pid, name=name, description=name, system=system))
        session.commit()
    return pid


def test_list_projects_empty(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_projects"] == []
    assert body["current_project"] is None


def test_create_project(client):
    resp = client.post("/projects", json={"project_name": "Research"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "Research" in body["response"]
    assert body["current_project"] in body["available_projects"]
    assert "Research" in body["project_names"].values()


def test_create_seeds_user_profile_into_uploads(client, temp_memory_root):
    resp = client.post("/projects", json={"project_name": "Seeded"})
    assert resp.status_code == 200
    pid = resp.json()["current_project"]

    profile_path = temp_memory_root / pid / "uploads" / "USER_PROFILE.txt"
    assert profile_path.is_file()
    assert "User Profile" in profile_path.read_text(encoding="utf-8")


def test_user_profile_get_missing_is_empty(client, db):
    pid = _make_project(db, name="Profile")
    resp = client.get(f"/projects/{pid}/user_profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exists"] is False
    assert body["content"] == ""
    assert body["filename"] == "USER_PROFILE.txt"


def test_user_profile_put_then_get_roundtrip(client, db, temp_memory_root):
    pid = _make_project(db, name="Profile")
    text = "# User Profile\n\n## About Me\nTest user.\n"
    put = client.put(f"/projects/{pid}/user_profile", json={"content": text})
    assert put.status_code == 200
    assert put.json()["rebuild_status"] == "completed"

    saved = (temp_memory_root / pid / "uploads" / "USER_PROFILE.txt").read_text(encoding="utf-8")
    assert saved == text

    got = client.get(f"/projects/{pid}/user_profile")
    assert got.json()["content"] == text
    assert got.json()["exists"] is True


def test_user_profile_put_requires_content_string(client, db):
    pid = _make_project(db, name="Profile")
    resp = client.put(f"/projects/{pid}/user_profile", json={})
    assert resp.status_code == 400


def test_create_duplicate_name_conflicts(client):
    client.post("/projects", json={"project_name": "Dup"})
    resp = client.post("/projects", json={"project_name": "dup"})  # case-insensitive
    assert resp.status_code == 409


def test_create_without_name_is_bad_request(client):
    resp = client.post("/projects", json={})
    assert resp.status_code == 400


def test_switch_to_existing_project(client, db):
    pid = _make_project(db, name="Existing")
    resp = client.post("/projects", json={"project_id": pid})
    assert resp.status_code == 200
    assert resp.json()["current_project"] == pid
    assert "Switched" in resp.json()["response"]


def test_switch_to_missing_project_404(client):
    resp = client.post("/projects", json={"project_id": "does-not-exist"})
    assert resp.status_code == 404


def test_rename_project(client, db):
    pid = _make_project(db, name="OldName")
    resp = client.patch(f"/projects/{pid}", json={"project_name": "NewName"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "NewName"


def test_rename_to_existing_name_conflicts(client, db):
    _make_project(db, name="Taken")
    pid = _make_project(db, name="Mine")
    resp = client.patch(f"/projects/{pid}", json={"project_name": "taken"})
    assert resp.status_code == 409


def test_rename_system_project_blocked(client, db):
    pid = _make_project(db, name="Sys", system=True)
    resp = client.patch(f"/projects/{pid}", json={"project_name": "Whatever"})
    assert resp.status_code == 400


def test_rename_missing_project_404(client):
    resp = client.patch("/projects/nope", json={"project_name": "X"})
    assert resp.status_code == 404


def test_rename_no_fields_bad_request(client, db):
    pid = _make_project(db, name="Plain")
    resp = client.patch(f"/projects/{pid}", json={})
    assert resp.status_code == 400


def test_delete_project(client, db):
    pid = _make_project(db, name="ToDelete")
    resp = client.request("DELETE", f"/projects/{pid}")
    assert resp.status_code == 200
    assert resp.json()["project_id"] == pid


def test_delete_system_project_blocked(client, db):
    pid = _make_project(db, name="SysDel", system=True)
    resp = client.request("DELETE", f"/projects/{pid}")
    assert resp.status_code == 400


def test_delete_missing_project_404(client):
    resp = client.request("DELETE", "/projects/missing")
    assert resp.status_code == 404


def test_project_detail(client, db):
    pid = _make_project(db, name="Detail")
    resp = client.get(f"/projects/{pid}")
    assert resp.status_code == 200
    proj = resp.json()["project"]
    assert proj["id"] == pid
    assert proj["name"] == "Detail"
    assert proj["system"] is False


def test_project_detail_missing_404(client):
    resp = client.get("/projects/missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /projects/{id}/dream/keep orchestration
#
# These pin the two-pass persist flow (tag -> append + summary -> finalize) and
# its key invariants (delete dream.json only on full success, filter remote
# items without research) without reaching the real tagger, daily store, FAISS
# cache, or sleep-summary writer. Those collaborators are unit-tested elsewhere;
# here we exercise the router orchestration so it can be refactored safely.
# ---------------------------------------------------------------------------

@pytest.fixture
def dream_keep_env(monkeypatch):
    """Patch the dream-keep collaborators with deterministic recording fakes.

    Returns a namespace recording ``tag``, ``append`` (persisted pairs),
    ``rebuild`` (daily cache rebuilds), and ``sleep_summary`` writes.
    """
    calls = SimpleNamespace(tag=[], append=[], rebuild=[], sleep_summary=[])
    memory_id_counter = itertools.count(1)

    def fake_tag_pair(user_text, assistant_text, previous_pair_text=None, project_id=None):
        calls.tag.append((user_text, assistant_text, previous_pair_text, project_id))
        return {"topics": "alpha, beta", "intent": "learn", "type": "fact", "semantic_handle": "h1"}

    monkeypatch.setattr(projects_module, "tag_pair", fake_tag_pair)
    monkeypatch.setattr(projects_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"])
    monkeypatch.setattr(projects_module, "generate_memory_id", lambda **kw: f"mem-{next(memory_id_counter)}")
    monkeypatch.setattr(projects_module, "append_pair", lambda *a, **k: calls.append.append((a, k)))
    monkeypatch.setattr(projects_module, "rebuild_daily_cache", lambda *a, **k: calls.rebuild.append((a, k)))
    monkeypatch.setattr(projects_module, "write_latest_sleep_summary", lambda **k: calls.sleep_summary.append(k))
    return calls


def _write_dream_json(root, pid, summary="proj summary"):
    proj_dir = root / pid
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "dream.json").write_text(
        json.dumps({"project_summary": summary, "items": []}),
        encoding="utf-8",
    )


def _simple_dream_item(item_id, question, answer):
    return {"id": item_id, "remember": True, "origin_text": question, "assistant_response": answer}


def test_dream_keep_persists_and_deletes_on_success(client, temp_memory_root, dream_keep_env):
    pid = "p1"
    _write_dream_json(temp_memory_root, pid)
    payload = {"items": [_simple_dream_item("i1", "Q1", "A1"), _simple_dream_item("i2", "Q2", "A2")]}

    resp = client.post(f"/projects/{pid}/dream/keep", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 2
    assert body["kept"] == 2
    assert body["failed"] == 0
    assert body["deleted_dream"] is True

    # Both pairs tagged + persisted; cache rebuilt once; sleep summary written.
    assert len(dream_keep_env.tag) == 2
    assert len(dream_keep_env.append) == 2
    assert len(dream_keep_env.rebuild) == 1
    assert len(dream_keep_env.sleep_summary) == 1

    # dream.json removed; dream_summary.md written with a rendered block.
    assert not (temp_memory_root / pid / "dream.json").exists()
    summary_md = (temp_memory_root / pid / "dream_summary.md").read_text(encoding="utf-8")
    assert "mem-" in summary_md


def test_dream_keep_rejects_non_list_items(client):
    resp = client.post("/projects/p1/dream/keep", json={"items": "nope"})
    assert resp.status_code == 400


def test_dream_keep_no_remembered_items_noops(client, dream_keep_env):
    resp = client.post(
        "/projects/p1/dream/keep",
        json={"items": [{"id": "i1", "remember": False, "origin_text": "Q", "assistant_response": "A"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 0
    assert body["kept"] == 0
    assert body["deleted_dream"] is False
    assert dream_keep_env.append == []


def test_dream_keep_filters_remote_without_research(client, dream_keep_env):
    payload = {"items": [{"id": "r1", "remember": True, "source_resolution": "answer_remote"}]}

    resp = client.post("/projects/p1/dream/keep", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 0
    assert body["filtered_remote_without_research"] == 1
    assert dream_keep_env.append == []


def test_dream_keep_partial_failure_preserves_dream_json(
    client, temp_memory_root, dream_keep_env, monkeypatch
):
    pid = "p1"
    _write_dream_json(temp_memory_root, pid)

    # Fail persistence of the second pair only.
    state = {"n": 0}

    def flaky_append(*a, **k):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("disk full")
        dream_keep_env.append.append((a, k))

    monkeypatch.setattr(projects_module, "append_pair", flaky_append)
    payload = {"items": [_simple_dream_item("i1", "Q1", "A1"), _simple_dream_item("i2", "Q2", "A2")]}

    resp = client.post(f"/projects/{pid}/dream/keep", json=payload)

    assert resp.status_code == 500
    body = resp.json()
    assert body["processed"] == 2
    assert body["kept"] == 1
    assert body["failed"] == 1
    assert body["deleted_dream"] is False

    # On partial failure dream.json is preserved for retry; no sleep summary.
    assert (temp_memory_root / pid / "dream.json").exists()
    assert dream_keep_env.sleep_summary == []
