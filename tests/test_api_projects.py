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
import os
from types import SimpleNamespace

import pytest
from app.api import projects as projects_module
from app.core.db_models import ChatMessage, Project
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session


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
    monkeypatch.setattr(
        projects_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"]
    )
    monkeypatch.setattr(
        projects_module, "generate_memory_id", lambda **kw: f"mem-{next(memory_id_counter)}"
    )
    monkeypatch.setattr(projects_module, "append_pair", lambda *a, **k: calls.append.append((a, k)))
    monkeypatch.setattr(
        projects_module, "rebuild_daily_cache", lambda *a, **k: calls.rebuild.append((a, k))
    )
    monkeypatch.setattr(
        projects_module, "write_latest_sleep_summary", lambda **k: calls.sleep_summary.append(k)
    )
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
    payload = {
        "items": [_simple_dream_item("i1", "Q1", "A1"), _simple_dream_item("i2", "Q2", "A2")]
    }

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
        json={
            "items": [
                {"id": "i1", "remember": False, "origin_text": "Q", "assistant_response": "A"}
            ]
        },
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
    payload = {
        "items": [_simple_dream_item("i1", "Q1", "A1"), _simple_dream_item("i2", "Q2", "A2")]
    }

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


# ---------------------------------------------------------------------------
# dream-view helpers (pure / file IO)
# ---------------------------------------------------------------------------


def test_validate_dream_payload_variants():
    assert projects_module._validate_dream_payload("not a dict") is None
    assert projects_module._validate_dream_payload({"project_summary": 5}) is None  # bad type
    assert projects_module._validate_dream_payload({"items": "nope"}) is None  # bad type
    out = projects_module._validate_dream_payload({"project_summary": "s", "items": [{"id": 1}]})
    assert out == {"project_summary": "s", "items": [{"id": 1}]}
    # Missing items default to [].
    assert projects_module._validate_dream_payload({"project_summary": "s"})["items"] == []


def test_read_latest_sleep_summary(temp_memory_root):
    pid = "p-sum"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    # Missing file -> None.
    assert projects_module._read_latest_sleep_summary(pid) is None
    # Empty file -> None.
    (proj / "latest_sleep_summary.md").write_text("   ", encoding="utf-8")
    assert projects_module._read_latest_sleep_summary(pid) is None
    # Present -> wrapped.
    (proj / "latest_sleep_summary.md").write_text("today we learned X", encoding="utf-8")
    out = projects_module._read_latest_sleep_summary(pid)
    assert out == {"project_summary": "today we learned X", "items": []}


def test_read_pending_dream_project_summary(temp_memory_root):
    pid = "p-pend"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    dream_path = str(proj / "dream.json")
    # Missing -> None.
    assert projects_module._read_pending_dream_project_summary(pid, dream_path) is None
    # Malformed JSON -> None (logged).
    (proj / "dream.json").write_text("{bad", encoding="utf-8")
    assert projects_module._read_pending_dream_project_summary(pid, dream_path) is None
    # Non-dict top-level -> None.
    (proj / "dream.json").write_text("[]", encoding="utf-8")
    assert projects_module._read_pending_dream_project_summary(pid, dream_path) is None
    # Valid summary -> string.
    (proj / "dream.json").write_text(json.dumps({"project_summary": "sum"}), encoding="utf-8")
    assert projects_module._read_pending_dream_project_summary(pid, dream_path) == "sum"
    # Blank summary -> None.
    (proj / "dream.json").write_text(json.dumps({"project_summary": "  "}), encoding="utf-8")
    assert projects_module._read_pending_dream_project_summary(pid, dream_path) is None


# ---------------------------------------------------------------------------
# GET /projects/{id}/dream
# ---------------------------------------------------------------------------


def test_get_dream_missing_falls_back_to_sleep_summary(client, temp_memory_root):
    pid = "p-dream"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "latest_sleep_summary.md").write_text("fallback summary", encoding="utf-8")
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 200
    assert resp.json()["dream"]["project_summary"] == "fallback summary"


def test_get_dream_missing_no_summary_returns_none(client, temp_memory_root):
    resp = client.get("/projects/no-dream/dream")
    assert resp.status_code == 200
    assert resp.json()["dream"] is None


def test_get_dream_empty_file_falls_back(client, temp_memory_root):
    pid = "p-empty-dream"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "dream.json").write_text("   ", encoding="utf-8")
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 200
    assert resp.json()["dream"] is None  # empty -> fallback (no summary present)


def test_get_dream_malformed_json_falls_back(client, temp_memory_root):
    pid = "p-bad-dream"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "dream.json").write_text("{not json", encoding="utf-8")
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 200
    assert resp.json()["dream"] is None


def test_get_dream_invalid_payload_falls_back(client, temp_memory_root):
    pid = "p-invalid-dream"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "dream.json").write_text("[1, 2, 3]", encoding="utf-8")  # not a dict
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 200
    assert resp.json()["dream"] is None


def test_get_dream_valid_filters_remote_without_research(client, temp_memory_root):
    pid = "p-valid-dream"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    items = [
        {"id": "ok", "source_resolution": "answer_local"},
        {"id": "drop", "source_resolution": "answer_remote"},  # filtered (no research)
    ]
    (proj / "dream.json").write_text(
        json.dumps({"project_summary": "s", "items": items}), encoding="utf-8"
    )
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 200
    returned = resp.json()["dream"]["items"]
    assert [i["id"] for i in returned] == ["ok"]


def test_get_dream_read_error_returns_500(client, temp_memory_root, monkeypatch):
    pid = "p-dream-err"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "dream.json").write_text(
        json.dumps({"project_summary": "s", "items": []}), encoding="utf-8"
    )

    def boom(_items):
        raise RuntimeError("filter blew up")

    monkeypatch.setattr(projects_module, "filter_remote_without_research", boom)
    resp = client.get(f"/projects/{pid}/dream")
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to read dream.json"


# ---------------------------------------------------------------------------
# memory-manager-backed endpoints (stats / chats / chat flags)
# ---------------------------------------------------------------------------


class _FakeMemoryManager:
    def __init__(self, history=None):
        self._history = history or []
        self.project_deques: dict = {}
        self.last_context_tokens_per_project: dict = {}
        self.set_calls: list = []

    def get_project_history(self, project_id):
        return self._history

    def set_last_context_tokens(self, project_id, tokens):
        self.set_calls.append((project_id, tokens))

    def get_active_pair_count(self, project_id):
        return 3


def test_project_stats_happy(client, db, temp_memory_root, monkeypatch):
    pid = _make_project(db, name="Stats")
    mm = _FakeMemoryManager(history=[{"content": "hello world"}])
    monkeypatch.setattr(projects_module, "start_daily_cache_rebuild", lambda *a, **k: None)
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: mm)
    monkeypatch.setattr(projects_module, "get_last_context_tokens", lambda pid: 0)
    monkeypatch.setattr(
        projects_module,
        "daily_stats",
        lambda pid: {
            "daily_index_size_bytes": 1,
            "daily_tokens_indexed": 2,
            "daily_vector_count": 4,
        },
    )
    resp = client.get(f"/projects/{pid}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["active_pairs"] == 3
    assert body["daily_vector_count"] == 4
    # context_tokens was 0 -> recomputed from history and cached.
    assert body["context_tokens"] > 0
    assert mm.set_calls and mm.set_calls[0][0] == pid


def test_project_stats_warm_failure_is_logged(client, db, monkeypatch, caplog):
    pid = _make_project(db, name="StatsWarm")
    mm = _FakeMemoryManager(history=[])
    monkeypatch.setattr(
        projects_module,
        "start_daily_cache_rebuild",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("warm down")),
    )
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: mm)
    monkeypatch.setattr(projects_module, "get_last_context_tokens", lambda pid: 5)
    monkeypatch.setattr(projects_module, "daily_stats", lambda pid: {})
    resp = client.get(f"/projects/{pid}/stats")
    assert resp.status_code == 200
    assert resp.json()["context_tokens"] == 5  # used cached value as-is


def test_get_chats_happy(client, monkeypatch):
    import datetime as _dt

    mm = _FakeMemoryManager(
        history=[
            {"id": 1, "role": "user", "content": "hi", "created_at": _dt.datetime(2026, 5, 7)},
            {
                "id": 2,
                "role": "assistant",
                "content": "hello",
                "created_at": "2026-05-07T00:00:00",
                "forget": False,
                "keep": True,
            },
        ]
    )
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: mm)
    resp = client.get("/projects/p1/chats")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert msgs[0]["created_at"] == "2026-05-07T00:00:00"  # datetime -> iso
    assert msgs[0]["forget"] is None  # user role -> None flags
    assert msgs[1]["keep"] is True


def test_get_chats_failure_returns_500(client, monkeypatch):
    def boom():
        raise RuntimeError("mm down")

    monkeypatch.setattr(projects_module, "get_memory_manager", boom)
    resp = client.get("/projects/p1/chats")
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to retrieve chats"


def _make_assistant_msg(engine, project_id):
    with Session(engine) as session:
        row = ChatMessage(project_id=project_id, role="assistant", content="a")
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def test_set_chat_forget_no_fields_400(client, db):
    pid = _make_project(db, name="Flags")
    msg_id = _make_assistant_msg(db, pid)
    resp = client.patch(f"/projects/{pid}/chats/{msg_id}", json={})
    assert resp.status_code == 400


def test_set_chat_forget_not_found_404(client, db):
    pid = _make_project(db, name="Flags404")
    resp = client.patch(f"/projects/{pid}/chats/99999", json={"forget": True})
    assert resp.status_code == 404


def test_set_chat_forget_updates_db_and_deque(client, db, monkeypatch):
    pid = _make_project(db, name="FlagsOK")
    msg_id = _make_assistant_msg(db, pid)
    mm = _FakeMemoryManager()
    mm.project_deques[pid] = [{"id": msg_id, "role": "assistant", "forget": False, "keep": False}]
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: mm)
    resp = client.patch(f"/projects/{pid}/chats/{msg_id}", json={"forget": True, "keep": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["forget"] is True and body["keep"] is True
    # In-memory deque mirrored.
    assert mm.project_deques[pid][0]["forget"] is True
    # DB row persisted.
    with Session(db) as session:
        row = session.get(ChatMessage, msg_id)
        assert row.forget is True and row.keep is True


def test_set_chat_forget_deque_update_failure_is_logged(client, db, monkeypatch, caplog):
    pid = _make_project(db, name="FlagsDeque")
    msg_id = _make_assistant_msg(db, pid)

    class _BadMM:
        @property
        def project_deques(self):
            raise RuntimeError("deque access failed")

    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: _BadMM())
    resp = client.patch(f"/projects/{pid}/chats/{msg_id}", json={"forget": True})
    # DB update still succeeds; deque mirror failure is swallowed + logged.
    assert resp.status_code == 200
    assert any("Failed updating in-memory chat flags" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# personality / system prompt
# ---------------------------------------------------------------------------


def test_get_personality_happy(client, monkeypatch):
    monkeypatch.setattr(projects_module, "load_project_personality", lambda pid: {"tone": "warm"})
    monkeypatch.setattr(projects_module, "load_project_system_prompt", lambda pid: "SYS")
    resp = client.get("/projects/p1/personality")
    assert resp.status_code == 200
    body = resp.json()
    assert body["personality"] == {"tone": "warm"}
    assert body["system_prompt"] == "SYS"
    assert body["system_prompt_bytes"] == 3


def test_get_personality_failure_500(client, monkeypatch):
    def boom(_pid):
        raise RuntimeError("load failed")

    monkeypatch.setattr(projects_module, "load_project_personality", boom)
    resp = client.get("/projects/p1/personality")
    assert resp.status_code == 500


def test_patch_personality_happy(client, monkeypatch):
    monkeypatch.setattr(projects_module, "load_project_personality", lambda pid: {"tone": "old"})
    monkeypatch.setattr(projects_module, "save_project_personality", lambda pid, data: data)
    resp = client.patch("/projects/p1/personality", json={"tone": "new"})
    assert resp.status_code == 200
    assert resp.json()["personality"]["tone"] == "new"


def test_patch_personality_validation_error_400(client, monkeypatch):
    monkeypatch.setattr(projects_module, "load_project_personality", lambda pid: {})

    def bad_save(pid, data):
        raise ValueError("bad creativity")

    monkeypatch.setattr(projects_module, "save_project_personality", bad_save)
    resp = client.patch("/projects/p1/personality", json={"creativity": 9})
    assert resp.status_code == 400
    assert "bad creativity" in resp.json()["error"]


def test_patch_personality_save_failure_500(client, monkeypatch):
    monkeypatch.setattr(projects_module, "load_project_personality", lambda pid: {})

    def boom(pid, data):
        raise RuntimeError("disk full")

    monkeypatch.setattr(projects_module, "save_project_personality", boom)
    resp = client.patch("/projects/p1/personality", json={"tone": "x"})
    assert resp.status_code == 500


def test_put_system_prompt_happy(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        projects_module, "save_project_system_prompt", lambda pid, content: saved.update(c=content)
    )
    resp = client.put("/projects/p1/system_prompt", json={"content": "new prompt"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "new prompt"
    assert saved["c"] == "new prompt"


def test_put_system_prompt_validation_error_400(client, monkeypatch):
    def bad(pid, content):
        raise ValueError("too long")

    monkeypatch.setattr(projects_module, "save_project_system_prompt", bad)
    resp = client.put("/projects/p1/system_prompt", json={"content": "x"})
    assert resp.status_code == 400


def test_put_system_prompt_save_failure_500(client, monkeypatch):
    def boom(pid, content):
        raise RuntimeError("disk full")

    monkeypatch.setattr(projects_module, "save_project_system_prompt", boom)
    resp = client.put("/projects/p1/system_prompt", json={"content": "x"})
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# user_profile error branches
# ---------------------------------------------------------------------------


def test_user_profile_get_read_error_500(client, db, temp_memory_root, monkeypatch):
    pid = _make_project(db, name="ProfileErr")
    path = projects_module._user_profile_path(pid)
    import os as _os

    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("x")

    real_open = open

    def boom_open(p, *a, **k):
        if p == path:
            raise OSError("read denied")
        return real_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", boom_open)
    resp = client.get(f"/projects/{pid}/user_profile")
    assert resp.status_code == 500


def test_user_profile_put_exceeds_max_size_400(client, db, temp_memory_root, settings_override):
    pid = _make_project(db, name="ProfileBig")
    settings_override(max_upload_mb=0)  # any non-empty content exceeds 0 bytes
    resp = client.put(f"/projects/{pid}/user_profile", json={"content": "too big"})
    assert resp.status_code == 400
    assert "exceeds max size" in resp.json()["error"]


def test_user_profile_put_write_error_500(client, db, temp_memory_root, monkeypatch):
    pid = _make_project(db, name="ProfileWrite")

    real_open = open

    def boom_open(p, *a, **k):
        if str(p).endswith("USER_PROFILE.txt") and "w" in (a[0] if a else k.get("mode", "")):
            raise OSError("write denied")
        return real_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", boom_open)
    resp = client.put(f"/projects/{pid}/user_profile", json={"content": "hi"})
    assert resp.status_code == 500


def test_user_profile_put_rebuild_failure_reports_status(client, db, temp_memory_root, monkeypatch):
    pid = _make_project(db, name="ProfileRebuild")

    def boom(_pid):
        raise RuntimeError("rag down")

    monkeypatch.setattr(projects_module, "rebuild_faiss_index", boom)
    resp = client.put(f"/projects/{pid}/user_profile", json={"content": "hi"})
    assert resp.status_code == 200
    assert resp.json()["rebuild_status"] == "failed"


# ---------------------------------------------------------------------------
# create / delete branches
# ---------------------------------------------------------------------------


def test_get_project_detail_failure_returns_500(client, db, monkeypatch):
    def boom():
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", boom)
    resp = client.get("/projects/anything")
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to retrieve project"


def test_rename_failure_returns_handled_error(client, db, monkeypatch):
    pid = _make_project(db, name="RenameErr")

    def boom():
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", boom)
    resp = client.patch(f"/projects/{pid}", json={"project_name": "new"})
    # handle_project_error maps generic failures to a 404 PROJECT_NOT_FOUND response.
    assert resp.status_code == 404


def test_rename_daily_rag_toggle_only(client, db):
    pid = _make_project(db, name="ToggleRag")
    resp = client.patch(f"/projects/{pid}", json={"daily_rag_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["daily_rag_enabled"] is False


def test_create_seed_failure_is_logged(client, temp_memory_root, monkeypatch, caplog):
    def boom(_pid):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(projects_module, "seed_project_defaults", boom)
    resp = client.post("/projects", json={"project_name": "SeedFail"})
    assert resp.status_code == 200  # creation still succeeds
    assert any("Failed to seed defaults" in r.message for r in caplog.records)


def test_create_rebuild_failure_is_logged(client, temp_memory_root, monkeypatch, caplog):
    def boom(_pid):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(projects_module, "rebuild_faiss_index", boom)
    resp = client.post("/projects", json={"project_name": "RebuildFail"})
    assert resp.status_code == 200
    assert any("RAG rebuild failed" in r.message for r in caplog.records)


def test_create_existing_profile_skips_copy(client, temp_memory_root, db, monkeypatch, caplog):
    # Pre-create the uploads dir + profile so the copy branch logs "already exists".
    import os as _os

    # The new project's id is unknown ahead of time; intercept makedirs to seed
    # the profile right after the uploads dir is created.
    real_makedirs = _os.makedirs

    def seeding_makedirs(path, *a, **k):
        real_makedirs(path, *a, **k)
        if str(path).endswith("uploads"):
            dst = _os.path.join(path, "USER_PROFILE.txt")
            if not _os.path.exists(dst):
                with open(dst, "w", encoding="utf-8") as f:
                    f.write("pre-existing")

    monkeypatch.setattr(projects_module.os, "makedirs", seeding_makedirs)
    resp = client.post("/projects", json={"project_name": "ProfileExists"})
    assert resp.status_code == 200
    assert any("already exists for project" in r.message for r in caplog.records)


def test_delete_project_removes_disk_directory(client, db, temp_memory_root):
    pid = _make_project(db, name="DeleteDisk")
    base = temp_memory_root / pid
    (base / "sub").mkdir(parents=True)
    (base / "daily.json").write_text("[]", encoding="utf-8")
    (base / "sub" / "f.txt").write_text("x", encoding="utf-8")
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 200
    assert not base.exists()


def test_delete_project_failure_returns_500(client, db, monkeypatch):
    pid = _make_project(db, name="DeleteErr")
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("session down")
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", flaky)
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to delete project"


# ---------------------------------------------------------------------------
# GET /projects listing: normalization, default selection, error
# ---------------------------------------------------------------------------


def test_list_projects_initializes_to_main(client, db):
    main_id = _make_project(db, name="Main")
    _make_project(db, name="Other")
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert resp.json()["current_project"] == main_id


def test_list_projects_falls_back_to_first_when_no_main(client, db):
    pid = _make_project(db, name="OnlyOne")
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert resp.json()["current_project"] == pid


def test_list_projects_normalizes_legacy_name(client, db):
    pid = _make_project(db, name="Main")
    legacy = _make_project(db, name="Main")  # placeholder id we then rename below
    with Session(db) as session:
        obj = session.get(Project, legacy)
        obj.name = f"Project {legacy}"  # legacy 'Project {id}' pattern
        session.add(obj)
        session.commit()
    resp = client.get("/projects")
    assert resp.status_code == 200
    names = resp.json()["project_names"]
    assert names[legacy] == legacy  # normalized to bare id
    assert names[pid] == "Main"


def test_list_projects_failure_returns_404(client, monkeypatch):
    def boom():
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", boom)
    resp = client.get("/projects")
    assert resp.status_code == 404  # handle_project_error


# ---------------------------------------------------------------------------
# create: seeding sub-branches
# ---------------------------------------------------------------------------


def test_create_missing_default_profile_warns(client, temp_memory_root, monkeypatch, caplog):
    real_isfile = projects_module.os.path.isfile

    def no_default(path):
        if str(path).endswith("config/defaults/USER_PROFILE.txt"):
            return False
        return real_isfile(path)

    monkeypatch.setattr(projects_module.os.path, "isfile", no_default)
    resp = client.post("/projects", json={"project_name": "NoDefault"})
    assert resp.status_code == 200
    assert any("created without baseline knowledge" in r.message for r in caplog.records)


def test_create_seed_profile_outer_failure_logged(client, temp_memory_root, monkeypatch, caplog):
    real_makedirs = projects_module.os.makedirs

    def boom_makedirs(path, *a, **k):
        if str(path).endswith("uploads"):
            raise OSError("mkdir denied")
        return real_makedirs(path, *a, **k)

    monkeypatch.setattr(projects_module.os, "makedirs", boom_makedirs)
    resp = client.post("/projects", json={"project_name": "MkdirFail"})
    assert resp.status_code == 200  # creation succeeds; profile seeding swallowed
    assert any("Failed seeding user profile" in r.message for r in caplog.records)


def test_create_listing_normalizes_legacy_name(client, db, temp_memory_root):
    legacy = _make_project(db, name="LegacyHolder")
    with Session(db) as session:
        obj = session.get(Project, legacy)
        obj.name = f"Project {legacy}"
        session.add(obj)
        session.commit()
    resp = client.post("/projects", json={"project_name": "FreshOne"})
    assert resp.status_code == 200
    assert resp.json()["project_names"][legacy] == legacy


def test_create_outer_failure_returns_404(client, monkeypatch):
    def boom():
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", boom)
    resp = client.post("/projects", json={"project_name": "Boom"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# delete: cleanup sub-branches
# ---------------------------------------------------------------------------


def test_delete_current_project_resets_to_main(client, db, temp_memory_root, reset_projects_state):
    main_id = _make_project(db, name="Main")
    victim = _make_project(db, name="Victim")
    projects_module._current_project = victim
    resp = client.delete(f"/projects/{victim}")
    assert resp.status_code == 200
    assert resp.json()["current_project"] == main_id


def test_delete_file_removal_failures_are_logged(client, db, temp_memory_root, monkeypatch, caplog):
    pid = _make_project(db, name="RemoveFail")
    base = temp_memory_root / pid
    (base / "sub").mkdir(parents=True)
    (base / "f.txt").write_text("x", encoding="utf-8")

    def boom_remove(_path):
        raise OSError("remove denied")

    def boom_rmdir(_path):
        raise OSError("rmdir denied")

    monkeypatch.setattr(projects_module.os, "remove", boom_remove)
    monkeypatch.setattr(projects_module.os, "rmdir", boom_rmdir)
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 200
    assert any("Failed removing file" in r.message for r in caplog.records)


def test_delete_memory_manager_pop_failures_logged(client, db, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    pid = _make_project(db, name="MMPops")

    class _PopFail:
        def pop(self, *a, **k):
            raise RuntimeError("pop failed")

    mm = SimpleNamespace(project_deques=_PopFail(), last_context_tokens_per_project=_PopFail())
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: mm)
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 200
    assert any("Failed clearing project deque" in r.message for r in caplog.records)
    assert any("Failed clearing last_rolled_off_pair" in r.message for r in caplog.records)


def test_delete_memory_manager_unavailable_logged(client, db, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    pid = _make_project(db, name="MMGone")

    def boom():
        raise RuntimeError("mm unavailable")

    monkeypatch.setattr(projects_module, "get_memory_manager", boom)
    resp = client.delete(f"/projects/{pid}")
    assert resp.status_code == 200
    assert any("Memory manager cleanup failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# stats: error sub-branches
# ---------------------------------------------------------------------------


def test_project_stats_index_getsize_failure_logged(
    client, db, temp_memory_root, monkeypatch, caplog
):
    import logging

    caplog.set_level(logging.INFO)
    pid = _make_project(db, name="StatsGetsize")
    faiss_dir = temp_memory_root / pid / "faiss"
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "index.faiss").write_text("x", encoding="utf-8")
    monkeypatch.setattr(projects_module, "start_daily_cache_rebuild", lambda *a, **k: None)
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: _FakeMemoryManager())
    monkeypatch.setattr(projects_module, "get_last_context_tokens", lambda pid: 5)
    monkeypatch.setattr(projects_module, "daily_stats", lambda pid: {})

    def boom_getsize(_p):
        raise OSError("stat failed")

    monkeypatch.setattr(projects_module.os.path, "getsize", boom_getsize)
    resp = client.get(f"/projects/{pid}/stats")
    assert resp.status_code == 200
    assert resp.json()["index_size_bytes"] == 0
    assert any("Failed reading file size" in r.message for r in caplog.records)


def test_project_stats_context_recompute_failure_left_zero(client, db, monkeypatch):
    pid = _make_project(db, name="StatsRecompute")

    class _BadHistoryMM(_FakeMemoryManager):
        def get_project_history(self, project_id):
            raise RuntimeError("history gone")

        def get_active_pair_count(self, project_id):
            raise RuntimeError("count gone")

    monkeypatch.setattr(projects_module, "start_daily_cache_rebuild", lambda *a, **k: None)
    monkeypatch.setattr(projects_module, "get_memory_manager", lambda: _BadHistoryMM())
    monkeypatch.setattr(projects_module, "get_last_context_tokens", lambda pid: 0)
    monkeypatch.setattr(projects_module, "daily_stats", lambda pid: {})
    resp = client.get(f"/projects/{pid}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_tokens"] == 0  # recompute failed -> left at zero
    assert body["active_pairs"] == 0  # count failed -> zero


# ---------------------------------------------------------------------------
# set_chat_forget: outer 500
# ---------------------------------------------------------------------------


def test_set_chat_forget_failure_returns_500(client, db, monkeypatch):
    pid = _make_project(db, name="FlagsBoom")

    def boom():
        raise RuntimeError("session down")

    monkeypatch.setattr(projects_module, "get_session", boom)
    resp = client.patch(f"/projects/{pid}/chats/1", json={"forget": True})
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# dream-keep: error sub-branches
# ---------------------------------------------------------------------------


def test_read_latest_sleep_summary_read_error(temp_memory_root, monkeypatch, caplog):
    pid = "p-sum-err"
    proj = temp_memory_root / pid
    proj.mkdir(parents=True)
    (proj / "latest_sleep_summary.md").write_text("text", encoding="utf-8")

    def boom_open(*a, **k):
        raise OSError("read denied")

    monkeypatch.setattr("builtins.open", boom_open)
    assert projects_module._read_latest_sleep_summary(pid) is None
    assert any("Failed reading latest dream summary" in r.message for r in caplog.records)


def test_dream_keep_skips_empty_pairs(client, temp_memory_root, dream_keep_env):
    # remember=True but empty texts -> no persistable pair (warning, skipped).
    payload = {
        "items": [{"id": "i1", "remember": True, "origin_text": "", "assistant_response": ""}]
    }
    resp = client.post("/projects/p1/dream/keep", json=payload)
    assert resp.status_code == 200
    assert resp.json()["processed"] == 0
    assert dream_keep_env.append == []


def test_dream_keep_tagger_failure_persists_without_tags(
    client, temp_memory_root, dream_keep_env, monkeypatch
):
    pid = "p1"
    _write_dream_json(temp_memory_root, pid)

    def boom_tag(*a, **k):
        raise RuntimeError("tagger down")

    monkeypatch.setattr(projects_module, "tag_pair", boom_tag)
    resp = client.post(
        f"/projects/{pid}/dream/keep", json={"items": [_simple_dream_item("i1", "Q", "A")]}
    )
    assert resp.status_code == 200
    assert resp.json()["kept"] == 1  # persisted despite tagger failure


def test_dream_keep_rebuild_failure_blocks_delete(
    client, temp_memory_root, dream_keep_env, monkeypatch
):
    pid = "p1"
    _write_dream_json(temp_memory_root, pid)

    def boom_rebuild(*a, **k):
        raise RuntimeError("rebuild down")

    monkeypatch.setattr(projects_module, "rebuild_daily_cache", boom_rebuild)
    resp = client.post(
        f"/projects/{pid}/dream/keep", json={"items": [_simple_dream_item("i1", "Q", "A")]}
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["deleted_dream"] is False  # rebuild failure recorded -> not deleted
    assert (temp_memory_root / pid / "dream.json").exists()


def test_dream_keep_delete_failure_recorded(client, temp_memory_root, dream_keep_env, monkeypatch):
    pid = "p1"
    _write_dream_json(temp_memory_root, pid)

    real_remove = projects_module.os.remove

    def boom_remove(path):
        if str(path).endswith("dream.json"):
            raise OSError("remove denied")
        return real_remove(path)

    monkeypatch.setattr(projects_module.os, "remove", boom_remove)
    resp = client.post(
        f"/projects/{pid}/dream/keep", json={"items": [_simple_dream_item("i1", "Q", "A")]}
    )
    assert resp.status_code == 500
    assert resp.json()["deleted_dream"] is False


def test_dream_keep_outer_failure_returns_500(
    client, temp_memory_root, dream_keep_env, monkeypatch
):
    def boom(*a, **k):
        raise RuntimeError("tag stage exploded")

    monkeypatch.setattr(projects_module, "_tag_dream_pairs", boom)
    resp = client.post(
        "/projects/p1/dream/keep", json={"items": [_simple_dream_item("i1", "Q", "A")]}
    )
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to persist kept dream items"


def test_dream_keep_persist_filter_report_failure_logged(
    client, temp_memory_root, dream_keep_env, monkeypatch, caplog
):
    def boom(*a, **k):
        raise OSError("report write denied")

    monkeypatch.setattr(projects_module, "_write_persist_filter_report", boom)
    # A remote item without research triggers the filter report path.
    payload = {"items": [{"id": "r1", "remember": True, "source_resolution": "answer_remote"}]}
    resp = client.post("/projects/p1/dream/keep", json=payload)
    assert resp.status_code == 200
    assert any("Failed writing persist_filter_report" in r.message for r in caplog.records)


def test_prepare_dream_summary_paths_migrates_legacy_lock(temp_memory_root):
    pid = "p-lock"
    base = temp_memory_root / pid
    base.mkdir(parents=True)
    (base / "dream_summary.lock").write_text("", encoding="utf-8")
    _, _, lock_path = projects_module._prepare_dream_summary_paths(pid)
    assert lock_path.endswith("state/dream_summary.lock")
    assert os.path.isfile(lock_path)  # migrated into state/
    assert not (base / "dream_summary.lock").exists()


def test_prepare_dream_summary_paths_migration_failure_logged(
    temp_memory_root, monkeypatch, caplog
):
    pid = "p-lock-err"
    base = temp_memory_root / pid
    base.mkdir(parents=True)
    (base / "dream_summary.lock").write_text("", encoding="utf-8")

    def boom_replace(_src, _dst):
        raise OSError("replace denied")

    monkeypatch.setattr(projects_module.os, "replace", boom_replace)
    projects_module._prepare_dream_summary_paths(pid)
    assert any("dream_summary lock migration failed" in r.message for r in caplog.records)
