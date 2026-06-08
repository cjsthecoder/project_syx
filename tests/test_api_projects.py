"""
Copyright (c) 2025-2026 Syx Project Contributors

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
