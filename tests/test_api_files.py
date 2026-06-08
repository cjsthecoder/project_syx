"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Contract tests for the files API router.

Exercises upload validation (extension, per-file, batch, and storage limits) and
the list/delete flows against an isolated temp DB and memory root. The FAISS
rebuild is patched to a no-op so uploads never reach embeddings/network.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import files as files_module


@pytest.fixture
def client(db, temp_memory_root, monkeypatch):
    monkeypatch.setattr(files_module, "rebuild_faiss_index", lambda *a, **k: "/fake/index")
    app = FastAPI()
    app.include_router(files_module.router)
    return TestClient(app)


def _txt(name="note.txt", content=b"hello world from syx"):
    return ("files", (name, content, "text/plain"))


def test_upload_text_file_succeeds(client):
    resp = client.post("/projects/p1/files", files=[_txt()])
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 1
    assert body["uploaded"][0]["filename"] == "note.txt"
    assert body["uploaded"][0]["status"] == "ok"
    assert body["rebuild_status"] == "completed"


def test_upload_rejects_unsupported_extension(client):
    resp = client.post("/projects/p1/files", files=[("files", ("doc.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 400
    assert "Unsupported file type" in str(resp.json())


def test_upload_enforces_per_file_limit(client, settings_override):
    settings_override(max_upload_mb=0)  # any non-empty file now exceeds
    resp = client.post("/projects/p1/files", files=[_txt()])
    assert resp.status_code == 400
    assert "exceeds max size" in str(resp.json())


def test_upload_enforces_batch_limit(client, settings_override):
    settings_override(max_upload_mb=10, max_batch_mb=0)
    resp = client.post("/projects/p1/files", files=[_txt()])
    assert resp.status_code == 400
    assert "Batch exceeds" in str(resp.json())


def test_upload_enforces_storage_limit(client, settings_override):
    settings_override(max_upload_mb=10, max_batch_mb=50, storage_limit_mb=0)
    resp = client.post("/projects/p1/files", files=[_txt()])
    assert resp.status_code == 400
    # Either the pre-existing-total guard or the post-batch guard may fire first.
    assert "limit" in str(resp.json()).lower()


def test_list_files_reflects_upload(client):
    client.post("/projects/p1/files", files=[_txt(name="a.txt")])
    resp = client.get("/projects/p1/files")
    assert resp.status_code == 200
    body = resp.json()
    assert [f["filename"] for f in body["files"]] == ["a.txt"]
    assert body["storage_bytes"] > 0


def test_delete_file(client):
    up = client.post("/projects/p1/files", files=[_txt(name="del.txt")])
    file_id = client.get("/projects/p1/files").json()["files"][0]["id"]
    resp = client.request("DELETE", f"/projects/p1/files/{file_id}")
    assert resp.status_code == 200
    assert resp.json()["rebuild_status"] == "completed"
    assert up.status_code == 200


def test_delete_missing_file_404(client):
    resp = client.request("DELETE", "/projects/p1/files/99999")
    assert resp.status_code == 404
