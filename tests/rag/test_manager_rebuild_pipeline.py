"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the embedding/index/persist pipeline in app.rag.manager_rebuild.

Exercises the rate-limit classifier, token trimming, single/parallel batch
embedding (including throttle and failure paths), FAISS index assembly from
ordered results, artifact persistence, per-file stat backfill, and the
end-to-end rebuild_faiss_index orchestration. The embedding client, settings,
and database session are faked; FAISS and NumPy are real.
"""

import json
import os
from types import SimpleNamespace

import app.rag.manager_rebuild as mr
import pytest
from app.rag.manager_index_io import (
    LTM_DOCSTORE_NAME,
    LTM_INDEX_FILE_NAME,
    LTM_INDEX_TO_ID_NAME,
)
from app.rag.manager_rebuild import (
    _assemble_index_from_results,
    _backfill_file_stats,
    _embed_batches_parallel,
    _embed_one_batch,
    _persist_index_artifacts,
    _prepare_embedding_batches,
    is_rate_limit_error_message,
    ltm_docstore_item_id,
    read_file_text,
    rebuild_faiss_index,
    trim_to_tokens,
)
from app.rag.syx_memory_artifact import render_memory_entry

# --- fakes ----------------------------------------------------------------


class _FakeLLM:
    """Embedding client stub returning fixed-dim vectors (or a chosen payload)."""

    def __init__(self, dim: int = 4, vectors=None, raise_exc: Exception | None = None):
        self._dim = dim
        self._vectors = vectors
        self._raise = raise_exc

    def embed(self, texts, model=None):
        if self._raise is not None:
            raise self._raise
        if self._vectors is not None:
            return SimpleNamespace(vectors=self._vectors)
        return SimpleNamespace(vectors=[[0.1] * self._dim for _ in texts])


class _FakeExec:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row=None):
        self._row = row
        self.added: list = []
        self.committed = False

    def exec(self, _stmt):
        return _FakeExec(self._row)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


# --- is_rate_limit_error_message ------------------------------------------


def test_is_rate_limit_error_message_matches_signatures():
    assert is_rate_limit_error_message(Exception("Rate limit reached")) is True
    assert is_rate_limit_error_message(Exception("Too Many Requests")) is True
    assert is_rate_limit_error_message(Exception("HTTP 429")) is True
    assert is_rate_limit_error_message(Exception("rate_limit_exceeded")) is True
    assert is_rate_limit_error_message(Exception("disk full")) is False


# --- trim_to_tokens -------------------------------------------------------


def test_trim_to_tokens_returns_string():
    out = trim_to_tokens("alpha beta gamma delta epsilon", 2)
    assert isinstance(out, str)
    assert len(out) <= len("alpha beta gamma delta epsilon")


# --- _prepare_embedding_batches missing metadata --------------------------


def test_prepare_embedding_batches_raises_when_metadata_missing():
    # Passing metadatas=None makes iter_token_batches emit None metas.
    with pytest.raises(RuntimeError, match="missing metadata"):
        _prepare_embedding_batches(
            ["a", "b"], None, max_tokens_per_request=250_000, model_name="m"  # type: ignore[arg-type]
        )


# --- _embed_one_batch -----------------------------------------------------


def test_embed_one_batch_packages_payload():
    payload = _embed_one_batch(
        3, ["a", "b"], [{"i": 0}, {"i": 1}], 7, llm=_FakeLLM(dim=4), model_name="m"
    )
    assert payload["batch_id"] == 3
    assert payload["texts"] == ["a", "b"]
    assert payload["metas"] == [{"i": 0}, {"i": 1}]
    assert payload["est_tokens"] == 7
    assert len(payload["vectors"]) == 2
    assert payload["elapsed_s"] >= 0.0


# --- _embed_batches_parallel ----------------------------------------------


def test_embed_batches_parallel_happy_collects_by_batch_id():
    prepared = [
        (["a"], [{"i": 0}], 1),
        (["b", "c"], [{"i": 1}, {"i": 2}], 2),
    ]
    results = _embed_batches_parallel(
        prepared, llm=_FakeLLM(dim=4), model_name="m", worker_count=2, project_id="p"
    )
    assert set(results.keys()) == {1, 2}
    assert len(results[2]["vectors"]) == 2


def test_embed_batches_parallel_raises_on_rate_limit(caplog):
    prepared = [(["a"], [{"i": 0}], 1)]
    llm = _FakeLLM(raise_exc=Exception("Rate limit exceeded"))
    with pytest.raises(RuntimeError, match="failed during embedding"):
        _embed_batches_parallel(prepared, llm=llm, model_name="m", worker_count=1, project_id="p")


def test_embed_batches_parallel_raises_on_generic_failure():
    prepared = [(["a"], [{"i": 0}], 1)]
    llm = _FakeLLM(raise_exc=Exception("kaboom"))
    with pytest.raises(RuntimeError, match="failed during embedding"):
        _embed_batches_parallel(prepared, llm=llm, model_name="m", worker_count=1, project_id="p")


# --- _assemble_index_from_results -----------------------------------------


def _result(batch_id, texts, metas, vectors):
    return {
        "batch_id": batch_id,
        "texts": texts,
        "metas": metas,
        "est_tokens": 1,
        "elapsed_s": 0.01,
        "vectors": vectors,
    }


def test_assemble_index_happy_builds_faiss_index_and_docstore():
    prepared = [(["a", "b"], [{"doc_id": "d", "chunk_seq": 0}, {"doc_id": "d", "chunk_seq": 1}], 2)]
    batch_results = {
        1: _result(
            1,
            ["a", "b"],
            [{"doc_id": "d", "chunk_seq": 0}, {"doc_id": "d", "chunk_seq": 1}],
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        )
    }
    index, index_dim, index_to_id, docstore = _assemble_index_from_results(
        prepared, batch_results, project_id="p", worker_count=1, max_req_tokens=100
    )
    assert index is not None
    assert index.ntotal == 2
    assert index_dim == 4
    assert index_to_id == ["d::chunk=0", "d::chunk=1"]
    assert docstore["d::chunk=0"]["text"] == "a"


def test_assemble_index_missing_batch_result_raises():
    prepared = [(["a"], [{"doc_id": "d", "chunk_seq": 0}], 1)]
    with pytest.raises(RuntimeError, match="missing embedding result"):
        _assemble_index_from_results(
            prepared, {}, project_id="p", worker_count=1, max_req_tokens=100
        )


def test_assemble_index_empty_vectors_skipped_yields_no_index(caplog):
    prepared = [(["a"], [{"doc_id": "d", "chunk_seq": 0}], 1)]
    batch_results = {1: _result(1, ["a"], [{"doc_id": "d", "chunk_seq": 0}], [])}
    index, index_dim, index_to_id, docstore = _assemble_index_from_results(
        prepared, batch_results, project_id="p", worker_count=1, max_req_tokens=100
    )
    assert index is None
    assert index_dim is None
    assert index_to_id == []
    assert docstore == {}


def test_assemble_index_dim_change_raises():
    prepared = [
        (["a"], [{"doc_id": "d", "chunk_seq": 0}], 1),
        (["b"], [{"doc_id": "d", "chunk_seq": 1}], 1),
    ]
    batch_results = {
        1: _result(1, ["a"], [{"doc_id": "d", "chunk_seq": 0}], [[1.0, 0.0, 0.0, 0.0]]),
        2: _result(2, ["b"], [{"doc_id": "d", "chunk_seq": 1}], [[1.0, 0.0, 0.0]]),  # dim 3
    }
    with pytest.raises(RuntimeError, match="Embedding dim changed"):
        _assemble_index_from_results(
            prepared, batch_results, project_id="p", worker_count=1, max_req_tokens=100
        )


# --- _persist_index_artifacts ---------------------------------------------


def _build_index(vectors):
    import faiss
    import numpy as np

    mat = np.array(vectors, dtype="float32")
    index = faiss.IndexFlatIP(mat.shape[1])
    index.add(mat)
    return index


def test_persist_index_artifacts_writes_all_files(tmp_path):
    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    index = _build_index([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    index_to_id = ["d::chunk=0", "d::chunk=1"]
    docstore = {
        "d::chunk=0": {"text": "a", "metadata": {"doc_id": "d", "chunk_seq": 0}},
        "d::chunk=1": {"text": "b", "metadata": {"doc_id": "d", "chunk_seq": 1}},
    }
    _persist_index_artifacts(
        project_id="p",
        faiss_dir=str(faiss_dir),
        index=index,
        index_dim=4,
        index_to_id=index_to_id,
        docstore=docstore,
        settings=SimpleNamespace(chunk_size=800, chunk_overlap=100),
    )
    assert (faiss_dir / LTM_INDEX_FILE_NAME).exists()
    assert json.loads((faiss_dir / LTM_INDEX_TO_ID_NAME).read_text()) == index_to_id
    assert (faiss_dir / LTM_DOCSTORE_NAME).exists()


def test_persist_index_artifacts_logs_when_adjacency_unbuildable(tmp_path, caplog):
    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    index = _build_index([[1.0, 0.0, 0.0, 0.0]])
    # Non-contiguous chunk_seq -> adjacency build returns None -> ok False (logged).
    docstore = {"d::chunk=2": {"text": "a", "metadata": {"doc_id": "d", "chunk_seq": 2}}}
    _persist_index_artifacts(
        project_id="p",
        faiss_dir=str(faiss_dir),
        index=index,
        index_dim=4,
        index_to_id=["d::chunk=2"],
        docstore=docstore,
        settings=SimpleNamespace(chunk_size=800, chunk_overlap=100),
    )
    assert any("failed to write adjacency index" in r.message for r in caplog.records)


def test_persist_index_artifacts_swallows_adjacency_exception(tmp_path, monkeypatch, caplog):
    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    index = _build_index([[1.0, 0.0, 0.0, 0.0]])

    def boom(**_k):
        raise RuntimeError("adjacency write blew up")

    monkeypatch.setattr(mr, "write_ltm_manifest_and_adjacency", boom)
    _persist_index_artifacts(
        project_id="p",
        faiss_dir=str(faiss_dir),
        index=index,
        index_dim=4,
        index_to_id=["d::chunk=0"],
        docstore={"d::chunk=0": {"text": "a", "metadata": {"doc_id": "d", "chunk_seq": 0}}},
        settings=SimpleNamespace(chunk_size=800, chunk_overlap=100),
    )
    assert any("exception writing adjacency index" in r.message for r in caplog.records)


# --- _backfill_file_stats -------------------------------------------------


def test_backfill_file_stats_updates_matching_row(monkeypatch):
    row = SimpleNamespace(
        project_id="p", filename="doc.md", token_count=0, page_count=1, embedding_status="pending"
    )
    session = _FakeSession(row=row)
    monkeypatch.setattr(mr, "get_session", lambda: session)
    _backfill_file_stats("p", {"doc.md": 123}, {"doc.md": 1})
    assert row.token_count == 123
    assert row.embedding_status == "indexed"
    assert session.committed is True


def test_backfill_file_stats_no_matching_row_still_commits(monkeypatch):
    session = _FakeSession(row=None)
    monkeypatch.setattr(mr, "get_session", lambda: session)
    _backfill_file_stats("p", {"missing.md": 5}, {"missing.md": 1})
    assert session.committed is True
    assert session.added == []


def test_backfill_file_stats_swallows_db_error(monkeypatch, caplog):
    def boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(mr, "get_session", boom)
    _backfill_file_stats("p", {"doc.md": 1}, {"doc.md": 1})  # must not raise
    assert any("failed backfilling file stats" in r.message for r in caplog.records)


# --- rebuild_faiss_index (orchestration) ----------------------------------


def _settings(tmp_path, **overrides):
    base = dict(
        chunk_size=2000,
        chunk_overlap=100,
        memory_root=str(tmp_path),
        max_embed_tokens_per_request=250_000,
        rag_embed_rebuild_workers=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _wire_rebuild(monkeypatch, tmp_path, llm, *, settings=None):
    monkeypatch.setattr(mr, "get_settings", lambda: settings or _settings(tmp_path))
    monkeypatch.setattr(mr, "get_active_embedding_model", lambda: "fake-model")
    monkeypatch.setattr(mr, "get_embedding_client", lambda: llm)
    monkeypatch.setattr(mr, "get_session", lambda: _FakeSession(row=None))


def _make_upload(tmp_path, project_id, filename, content):
    uploads = tmp_path / project_id / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / filename).write_text(content, encoding="utf-8")


def test_rebuild_faiss_index_no_uploads_returns_dir_without_index(tmp_path, monkeypatch):
    _wire_rebuild(monkeypatch, tmp_path, _FakeLLM(dim=4))
    faiss_dir = rebuild_faiss_index("proj-empty")
    assert os.path.isdir(faiss_dir)
    assert not os.path.exists(os.path.join(faiss_dir, LTM_INDEX_FILE_NAME))


def test_rebuild_faiss_index_builds_and_persists(tmp_path, monkeypatch):
    _make_upload(tmp_path, "proj", "notes.md", "Hello world, this is a memory note for indexing.")
    _wire_rebuild(monkeypatch, tmp_path, _FakeLLM(dim=4))
    faiss_dir = rebuild_faiss_index("proj")
    assert os.path.exists(os.path.join(faiss_dir, LTM_INDEX_FILE_NAME))
    assert os.path.exists(os.path.join(faiss_dir, LTM_DOCSTORE_NAME))
    assert os.path.exists(os.path.join(faiss_dir, LTM_INDEX_TO_ID_NAME))


def test_rebuild_faiss_index_empty_vectors_returns_dir_without_index(tmp_path, monkeypatch):
    _make_upload(tmp_path, "proj2", "notes.md", "Some content to chunk and embed.")
    # Embedding client returns no vectors -> assembly yields no index -> early return.
    _wire_rebuild(monkeypatch, tmp_path, _FakeLLM(vectors=[]))
    faiss_dir = rebuild_faiss_index("proj2")
    assert not os.path.exists(os.path.join(faiss_dir, LTM_INDEX_FILE_NAME))


# --- read_file_text -------------------------------------------------------


def test_read_file_text_unsupported_extension_returns_empty(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG")
    assert read_file_text(str(path)) == []


def test_read_file_text_plain_file_whole_file_region(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("just plain content, no Syx markers", encoding="utf-8")
    regions = read_file_text(str(path), artifact_path="plain.md")
    assert len(regions) == 1
    text, meta = regions[0]
    assert text.startswith("just plain")
    assert meta == {"filename": "plain.md"}


def test_read_file_text_parses_syx_entries_into_regions(tmp_path):
    mid1 = "mem_20260507_214200_a8f3"
    mid2 = "mem_20260507_214201_b8f3"
    entry1 = render_memory_entry(
        memory_id=mid1,
        metadata={"memory_id": mid1, "entry_type": "chat_pair"},
        user_text="hello",
        assistant_text="hi there",
    )
    entry2 = render_memory_entry(
        memory_id=mid2,
        metadata={"memory_id": mid2, "entry_type": "chat_pair"},
        user_text="second",
        assistant_text="reply",
    )
    path = tmp_path / "mem.md"
    path.write_text(entry1 + entry2, encoding="utf-8")

    regions = read_file_text(str(path), artifact_path="mem.md")
    assert len(regions) == 2
    _text, meta = regions[0]
    assert meta["filename"] == "mem.md"
    assert meta["memory_id"] == mid1
    assert meta["doc_id"] == f"mem.md::memory_id={mid1}"
    assert meta["source_document_id"] == f"mem.md::memory_id={mid1}"
    assert meta["entry_start_line"] >= 1


def test_read_file_text_malformed_markers_fall_back_to_whole_file(tmp_path, caplog):
    mid = "mem_20260507_214200_a8f3"
    # begin marker without a matching end marker -> structural warning -> fallback.
    content = f"<!-- begin syx:memory_id={mid} -->\nbody without end marker\n"
    path = tmp_path / "broken.md"
    path.write_text(content, encoding="utf-8")

    regions = read_file_text(str(path), artifact_path="broken.md")
    assert len(regions) == 1
    text, meta = regions[0]
    assert meta == {"filename": "broken.md"}  # whole-file fallback
    assert text == content


# --- ltm_docstore_item_id -------------------------------------------------


def test_ltm_docstore_item_id_defaults():
    assert ltm_docstore_item_id({"doc_id": "d", "chunk_seq": 3}) == "d::chunk=3"
    assert ltm_docstore_item_id({}) == "::chunk=0"
    assert ltm_docstore_item_id(None) == "::chunk=0"
