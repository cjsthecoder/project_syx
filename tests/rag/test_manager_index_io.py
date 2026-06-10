"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for app.rag.manager_index_io.

Covers atomic JSON write, tolerant JSON load, doc_id derivation, row
normalization, cosine remapping, best-effort directory clearing, adjacency-list
construction (contiguity rules + error guards), and manifest/adjacency sidecar
persistence.
"""

import json
import os

import app.rag.manager_index_io as io_mod
import numpy as np
import pytest
from app.rag.manager_index_io import (
    ADJACENCY_SCHEMA_VERSION,
    LTM_ADJACENCY_INDEX_NAME,
    LTM_MANIFEST_NAME,
    atomic_write_json,
    build_ltm_adjacency_lists,
    clear_dir_contents,
    cosine_to_01,
    ltm_doc_id,
    normalize_rows,
    safe_load_json,
    uploads_relative_doc_id,
    write_ltm_manifest_and_adjacency,
)

# --- atomic_write_json / safe_load_json -----------------------------------


def test_atomic_write_json_writes_and_cleans_tmp(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(str(path), {"b": 2, "a": 1})
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}
    assert not (tmp_path / "out.json.tmp").exists()  # temp file replaced away


def test_safe_load_json_roundtrip(tmp_path):
    path = tmp_path / "x.json"
    atomic_write_json(str(path), {"k": "v"})
    assert safe_load_json(str(path)) == {"k": "v"}


def test_safe_load_json_missing_returns_none(tmp_path):
    assert safe_load_json(str(tmp_path / "nope.json")) is None


def test_safe_load_json_invalid_returns_none(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert safe_load_json(str(path)) is None


# --- uploads_relative_doc_id / ltm_doc_id ---------------------------------


def test_uploads_relative_doc_id_normalizes_separators(tmp_path):
    uploads = tmp_path / "uploads"
    file_path = uploads / "sub" / "doc.txt"
    out = uploads_relative_doc_id(str(uploads), str(file_path))
    assert out == "sub/doc.txt"


def test_uploads_relative_doc_id_falls_back_to_basename(monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("no relative path")

    monkeypatch.setattr(os.path, "relpath", boom)
    assert uploads_relative_doc_id("/uploads", "/elsewhere/file.txt") == "file.txt"


def test_ltm_doc_id_returns_filename_or_none():
    assert ltm_doc_id("notes.txt", None) == "notes.txt"
    assert ltm_doc_id("notes.txt", 5) == "notes.txt"  # page number ignored
    assert ltm_doc_id("", None) is None
    assert ltm_doc_id(None, None) is None
    assert ltm_doc_id(123, None) is None  # non-string


# --- normalize_rows / cosine_to_01 ----------------------------------------


def test_normalize_rows_empty_returns_float32_empty():
    out = normalize_rows(np.zeros((0, 3)))
    assert out.size == 0
    assert out.dtype == np.float32


def test_normalize_rows_unit_normalizes_and_keeps_zero_rows():
    v = np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 0.0]], dtype="float32")
    out = normalize_rows(v)
    assert out[0] == pytest.approx([0.6, 0.8, 0.0])  # 3/5, 4/5
    assert out[1] == pytest.approx([0.0, 0.0, 0.0])  # zero row left as-is


def test_cosine_to_01_maps_and_clamps():
    assert cosine_to_01(0.0) == 0.5
    assert cosine_to_01(1.0) == 1.0
    assert cosine_to_01(-1.0) == 0.0
    assert cosine_to_01(2.0) == 1.0  # clamped above
    assert cosine_to_01(-3.0) == 0.0  # clamped below


def test_cosine_to_01_non_numeric_returns_zero():
    assert cosine_to_01("nan-ish") == 0.0


# --- clear_dir_contents ----------------------------------------------------


def test_clear_dir_contents_missing_dir_is_noop(tmp_path):
    clear_dir_contents(str(tmp_path / "nope"))  # must not raise


def test_clear_dir_contents_removes_all_files(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    clear_dir_contents(str(tmp_path))
    assert list(tmp_path.rglob("*.txt")) == []  # all files gone


def test_clear_dir_contents_logs_and_continues_on_remove_failure(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("a")

    def boom(_path):
        raise OSError("permission denied")

    monkeypatch.setattr(io_mod.os, "remove", boom)
    clear_dir_contents(str(tmp_path))  # best-effort; swallows per-file failure
    assert (tmp_path / "a.txt").exists()  # not removed, but no exception raised


def test_clear_dir_contents_logs_on_walk_failure(tmp_path, monkeypatch):
    def boom(_path):
        raise RuntimeError("walk broke")

    monkeypatch.setattr(io_mod.os, "walk", boom)
    clear_dir_contents(str(tmp_path))  # top-level guard swallows the error


# --- build_ltm_adjacency_lists --------------------------------------------


def _entry(doc_id, chunk_seq):
    return {"metadata": {"doc_id": doc_id, "chunk_seq": chunk_seq}}


def test_build_adjacency_contiguous_per_doc():
    docstore = {
        "d1::0": _entry("d1", 0),
        "d1::1": _entry("d1", 1),
        "d2::0": _entry("d2", 0),
    }
    out = build_ltm_adjacency_lists(docstore=docstore, index_to_id=["d1::1", "d1::0", "d2::0"])
    assert out == {"d1": ["d1::0", "d1::1"], "d2": ["d2::0"]}  # sorted by chunk_seq


def test_build_adjacency_skips_invalid_doc_id_and_seq():
    docstore = {
        "ok::0": _entry("ok", 0),
        "nostr": {"metadata": {"doc_id": 123, "chunk_seq": 0}},  # non-string doc_id
        "badseq": {"metadata": {"doc_id": "ok", "chunk_seq": "x"}},  # non-int seq
    }
    out = build_ltm_adjacency_lists(docstore=docstore, index_to_id=["ok::0", "nostr", "badseq"])
    assert out == {"ok": ["ok::0"]}


def test_build_adjacency_non_contiguous_returns_none():
    docstore = {"d1::0": _entry("d1", 0), "d1::2": _entry("d1", 2)}  # gap at 1
    assert build_ltm_adjacency_lists(docstore=docstore, index_to_id=["d1::0", "d1::2"]) is None


def test_build_adjacency_does_not_start_at_zero_returns_none():
    docstore = {"d1::1": _entry("d1", 1), "d1::2": _entry("d1", 2)}
    assert build_ltm_adjacency_lists(docstore=docstore, index_to_id=["d1::1", "d1::2"]) is None


def test_build_adjacency_error_returns_none():
    # Non-iterable index_to_id triggers the defensive guard -> None.
    assert build_ltm_adjacency_lists(docstore={}, index_to_id=123) is None  # type: ignore[arg-type]


# --- write_ltm_manifest_and_adjacency -------------------------------------


def test_write_manifest_and_adjacency_happy(tmp_path):
    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    docstore = {"d1::0": _entry("d1", 0), "d1::1": _entry("d1", 1)}
    ok = write_ltm_manifest_and_adjacency(
        project_id="p",
        faiss_dir=str(faiss_dir),
        index_dim=3,
        chunk_size=800,
        chunk_overlap=100,
        docstore=docstore,
        index_to_id=["d1::0", "d1::1"],
    )
    assert ok is True
    adj = json.loads((faiss_dir / LTM_ADJACENCY_INDEX_NAME).read_text())
    assert adj["schema_version"] == ADJACENCY_SCHEMA_VERSION
    assert adj["by_doc_id"] == {"d1": ["d1::0", "d1::1"]}
    manifest = json.loads((faiss_dir / LTM_MANIFEST_NAME).read_text())
    assert manifest["chunk_size"] == 800
    assert manifest["index_dim"] == 3
    assert manifest["adjacency_index"] == LTM_ADJACENCY_INDEX_NAME


def test_write_manifest_returns_false_when_adjacency_unbuildable(tmp_path):
    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    # Non-contiguous -> adjacency None -> False, and no files written.
    docstore = {"d1::0": _entry("d1", 0), "d1::2": _entry("d1", 2)}
    ok = write_ltm_manifest_and_adjacency(
        project_id="p",
        faiss_dir=str(faiss_dir),
        index_dim=3,
        chunk_size=800,
        chunk_overlap=100,
        docstore=docstore,
        index_to_id=["d1::0", "d1::2"],
    )
    assert ok is False
    assert not (faiss_dir / LTM_ADJACENCY_INDEX_NAME).exists()


def test_write_manifest_returns_false_on_write_failure(tmp_path):
    # faiss_dir does not exist -> atomic_write_json open() fails -> False.
    docstore = {"d1::0": _entry("d1", 0)}
    ok = write_ltm_manifest_and_adjacency(
        project_id="p",
        faiss_dir=str(tmp_path / "missing_dir"),
        index_dim=3,
        chunk_size=800,
        chunk_overlap=100,
        docstore=docstore,
        index_to_id=["d1::0"],
    )
    assert ok is False
