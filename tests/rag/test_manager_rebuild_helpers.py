"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the pure helpers extracted from ``rebuild_faiss_index``.

Covers ``_collect_chunks_from_uploads`` (walking the uploads directory and
producing chunk texts/metadata plus per-file token and page sums) and
``_prepare_embedding_batches`` (packing chunks into token-budgeted batches).
These helpers contain no FAISS/embedding/threading I/O, so they are exercised
directly with real chunking and batching.
"""
import os
from types import SimpleNamespace

from app.rag.manager_rebuild import (
    _collect_chunks_from_uploads,
    _prepare_embedding_batches,
    count_tokens,
)


def _settings(chunk_size: int = 2000, chunk_overlap: int = 100) -> SimpleNamespace:
    return SimpleNamespace(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def test_collect_chunks_returns_empty_when_no_uploads_dir(tmp_path):
    uploads_dir = os.path.join(str(tmp_path), "uploads")  # not created
    texts, metadatas, token_sums, page_max = _collect_chunks_from_uploads(
        "proj-1", uploads_dir, _settings()
    )
    assert texts == []
    assert metadatas == []
    assert token_sums == {}
    assert page_max == {}


def test_collect_chunks_indexes_plain_markdown_file(tmp_path):
    uploads_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    content = "Hello world. This is a small uploaded document used for testing."
    file_path = os.path.join(uploads_dir, "doc.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    texts, metadatas, token_sums, page_max = _collect_chunks_from_uploads(
        "proj-1", uploads_dir, _settings()
    )

    # Small content fits in a single chunk.
    assert texts == [content]
    assert len(metadatas) == 1
    md = metadatas[0]
    assert md["project_id"] == "proj-1"
    assert md["filename"] == "doc.md"
    assert md["chunk_seq"] == 0
    assert md["chunk_index"] == 0
    assert md["chunk_id"] == 0
    # No Syx markers -> whole-file region keyed by the relative doc id.
    assert md["doc_id"] == "doc.md"
    assert md["source_document_id"] == "doc.md"
    assert isinstance(md["timestamp"], str) and md["timestamp"]

    # Per-file token sum matches counting the whole region once; one page.
    assert token_sums == {"doc.md": count_tokens(content)}
    assert page_max == {"doc.md": 1}


def test_collect_chunks_skips_unsupported_extensions(tmp_path):
    uploads_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    with open(os.path.join(uploads_dir, "image.png"), "wb") as f:
        f.write(b"\x89PNG\r\n")

    texts, metadatas, token_sums, page_max = _collect_chunks_from_uploads(
        "proj-1", uploads_dir, _settings()
    )
    assert texts == []
    assert metadatas == []
    assert token_sums == {}
    assert page_max == {}


def test_collect_chunks_splits_long_text_into_multiple_chunks(tmp_path):
    uploads_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    content = "word " * 500  # ~2500 chars, exceeds a small chunk window
    with open(os.path.join(uploads_dir, "long.md"), "w", encoding="utf-8") as f:
        f.write(content)

    texts, metadatas, _token_sums, _page_max = _collect_chunks_from_uploads(
        "proj-1", uploads_dir, _settings(chunk_size=400, chunk_overlap=40)
    )
    assert len(texts) > 1
    # chunk_seq is dense and ordered from 0.
    assert [m["chunk_seq"] for m in metadatas] == list(range(len(metadatas)))


def test_prepare_embedding_batches_single_batch_preserves_alignment():
    texts = ["alpha text", "beta text", "gamma text"]
    metadatas = [{"i": 0}, {"i": 1}, {"i": 2}]
    batches = _prepare_embedding_batches(
        texts, metadatas, max_tokens_per_request=250_000, model_name="text-embedding-3-small"
    )
    assert len(batches) == 1
    batch_texts, batch_metas, est_tokens = batches[0]
    assert batch_texts == texts
    assert batch_metas == metadatas
    assert isinstance(est_tokens, int) and est_tokens > 0


def test_prepare_embedding_batches_splits_when_budget_small():
    texts = ["alpha", "beta", "gamma"]
    metadatas = [{"i": 0}, {"i": 1}, {"i": 2}]
    # A 1-token budget forces each (>=1 token) item onto its own batch.
    batches = _prepare_embedding_batches(
        texts, metadatas, max_tokens_per_request=1, model_name="text-embedding-3-small"
    )
    assert len(batches) == 3
    assert [bt for bt, _bm, _et in batches] == [["alpha"], ["beta"], ["gamma"]]
    assert [bm for _bt, bm, _et in batches] == [[{"i": 0}], [{"i": 1}], [{"i": 2}]]


def test_prepare_embedding_batches_empty_input_yields_no_batches():
    assert _prepare_embedding_batches([], [], max_tokens_per_request=250_000, model_name="m") == []
