"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging
import sys
import types

faiss_module = types.ModuleType("faiss")
faiss_module.IndexFlatIP = type("IndexFlatIP", (), {})  # type: ignore[attr-defined]
faiss_module.write_index = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
faiss_module.read_index = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
sys.modules["faiss"] = faiss_module

numpy_module = types.ModuleType("numpy")
numpy_module.ndarray = object  # type: ignore[attr-defined]
numpy_module.float32 = "float32"  # type: ignore[attr-defined]
numpy_module.array = lambda value, dtype=None: value  # type: ignore[attr-defined]
sys.modules["numpy"] = numpy_module

embedding_factory_module = types.ModuleType("backend.app.embedding.factory")
embedding_factory_module.get_embedding_client = lambda: None  # type: ignore[attr-defined]
sys.modules["backend.app.embedding.factory"] = embedding_factory_module

embedding_batching_module = types.ModuleType("backend.app.embedding.batching")
embedding_batching_module.iter_token_batches = lambda *_args, **_kwargs: []  # type: ignore[attr-defined]
sys.modules["backend.app.embedding.batching"] = embedding_batching_module

from backend.app.rag.manager import _ltm_candidate_metadata
from backend.app.rag.manager_rebuild import ltm_docstore_item_id, read_file_text


def _bounded_entry(memory_id: str, metadata_block: str, body: str) -> str:
    return (
        f"<!-- begin syx:memory_id={memory_id} -->\n\n"
        "## Memory Entry\n\n"
        f"{metadata_block}"
        f"{body}\n"
        f"<!-- end syx:memory_id={memory_id} -->\n"
    )


def test_read_file_text_indexes_bounded_md_entries_only(tmp_path):
    first_id = "mem_20260507_160709_1aebd6c4"
    second_id = "mem_20260507_160710_2bcd1234"
    first_metadata = (
        "### Syx Metadata\n\n"
        "```yaml\n"
        f"memory_id: {first_id}\n"
        "entry_type: dream_output\n"
        "source: dream\n"
        "source_agent: syx\n"
        "source_scope: dream\n"
        "current_scope: ltm\n"
        "topics:\n"
        "  - token overlap\n"
        "  - semantic similarity\n"
        "semantic_handle: reliability of answer-source overlap\n"
        "```\n\n"
    )
    second_metadata = (
        "### Syx Metadata\n\n"
        "```yaml\n"
        f"memory_id: {second_id}\n"
        "entry_type: chat_pair\n"
        "source: chat\n"
        "source_scope: daily\n"
        "current_scope: ltm\n"
        "```\n\n"
    )
    path = tmp_path / "sleep.md"
    path.write_text(
        "---\nformat_version: 1\n---\n\n"
        "# Sleep Memory\n\n"
        + _bounded_entry(first_id, first_metadata, "first body\n")
        + "\nfile-level envelope that must not be indexed\n\n"
        + _bounded_entry(second_id, second_metadata, "second body\n"),
        encoding="utf-8",
    )

    regions = read_file_text(str(path), artifact_path="sleep/sleep.md")

    assert len(regions) == 2
    assert "file-level envelope" not in "\n".join(text for text, _meta in regions)
    first_text, first_meta = regions[0]
    assert "topics:" in first_text
    assert first_meta["memory_id"] == first_id
    assert first_meta["entry_type"] == "dream_output"
    assert first_meta["topics"] == ["token overlap", "semantic similarity"]
    assert first_meta["semantic_handle"] == "reliability of answer-source overlap"
    assert first_meta["source_document_id"] == f"sleep/sleep.md::memory_id={first_id}"
    assert first_meta["doc_id"] == first_meta["source_document_id"]
    assert first_meta["entry_start_line"] > 0
    assert first_meta["entry_end_line"] > first_meta["entry_start_line"]


def test_read_file_text_indexes_legacy_bounded_txt_without_yaml(tmp_path):
    memory_id = "mem_20260506_204555_027356fa"
    path = tmp_path / "sleep.txt"
    path.write_text(
        "---\nformat_version: 1\n---\n\n"
        "# Sleep Memory\n\n"
        f"<!-- begin syx:memory_id={memory_id} -->\n\n"
        "## Memory Entry: legacy tagged entry\n\n"
        "#timestamp: 05-06-2026_20:45:55\n"
        "#topics: memory management system, vector retrieval\n"
        "#semantic_handle: research agenda for memory management design\n\n"
        "legacy body\n"
        f"<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )

    regions = read_file_text(str(path), artifact_path="sleep/sleep.txt")

    assert len(regions) == 1
    text, meta = regions[0]
    assert "#topics: memory management system, vector retrieval" in text
    assert meta["memory_id"] == memory_id
    assert meta["artifact_path"] == "sleep/sleep.txt"
    assert meta["source_document_id"] == f"sleep/sleep.txt::memory_id={memory_id}"
    assert "entry_type" not in meta


def test_malformed_syx_marker_falls_back_to_whole_file(tmp_path, caplog):
    path = tmp_path / "bad.md"
    path.write_text(
        "envelope\n"
        "<!-- begin syx:memory_id=mem_20260507_160709_1aebd6c4 -->\n"
        "valid-looking body without matching end\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        regions = read_file_text(str(path), artifact_path="bad.md")

    assert len(regions) == 1
    assert regions[0][0].startswith("envelope\n")
    assert regions[0][1] == {"filename": "bad.md"}
    assert "falling back to whole-file indexing" in caplog.text


def test_invalid_yaml_metadata_warns_but_keeps_bounded_indexing(tmp_path, caplog):
    memory_id = "mem_20260507_160709_1aebd6c4"
    metadata = (
        "### Syx Metadata\n\n"
        "```yaml\n"
        "entry_type: chat_pair\n"
        "this line is invalid\n"
        "```\n\n"
    )
    path = tmp_path / "bad_metadata.md"
    path.write_text(_bounded_entry(memory_id, metadata, "body\n"), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        regions = read_file_text(str(path), artifact_path="bad_metadata.md")

    assert len(regions) == 1
    text, meta = regions[0]
    assert "this line is invalid" in text
    assert meta["memory_id"] == memory_id
    assert meta["entry_type"] == "chat_pair"
    assert meta["source_document_id"] == f"bad_metadata.md::memory_id={memory_id}"
    assert "invalid Syx metadata line" in caplog.text
    assert "falling back to whole-file indexing" not in caplog.text


def test_ltm_docstore_item_id_uses_source_document_chunk_pattern():
    memory_id = "mem_20260507_160709_1aebd6c4"
    source_document_id = f"dream/dream.md::memory_id={memory_id}"

    item_id = ltm_docstore_item_id({"doc_id": source_document_id, "chunk_seq": 2})

    assert item_id == f"{source_document_id}::chunk=2"


def test_ltm_candidate_metadata_exposes_syx_fields():
    memory_id = "mem_20260507_160709_1aebd6c4"

    metadata = _ltm_candidate_metadata(
        {
            "doc_id": f"dream/dream.md::memory_id={memory_id}",
            "source_document_id": f"dream/dream.md::memory_id={memory_id}",
            "chunk_seq": 0,
            "chunk_index": 0,
            "memory_id": memory_id,
            "entry_type": "dream_output",
            "source": "dream",
            "source_agent": "syx",
            "source_scope": "dream",
            "current_scope": "ltm",
            "semantic_handle": "useful memory attribution",
            "topics": ["retrieval", "attribution"],
            "artifact_path": "dream/dream.md",
            "entry_start_line": 10,
            "entry_end_line": 20,
        }
    )

    assert metadata["memory_id"] == memory_id
    assert metadata["entry_type"] == "dream_output"
    assert metadata["source"] == "dream"
    assert metadata["source_agent"] == "syx"
    assert metadata["source_scope"] == "dream"
    assert metadata["current_scope"] == "ltm"
    assert metadata["semantic_handle"] == "useful memory attribution"
    assert metadata["topics"] == ["retrieval", "attribution"]
    assert metadata["artifact_path"] == "dream/dream.md"
    assert metadata["entry_start_line"] == 10
    assert metadata["entry_end_line"] == 20
