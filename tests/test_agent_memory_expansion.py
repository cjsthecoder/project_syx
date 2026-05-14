"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

numpy_module = types.ModuleType("numpy")
numpy_module.ndarray = object  # type: ignore[attr-defined]
sys.modules.setdefault("numpy", numpy_module)

from app.agent_interface import entry_expansion
from app.agent_interface.entry_expansion import expand_agent_memory_snippets
from app.agent_interface.models import AgentMemorySnippet


def test_expands_bounded_snippet_from_artifact(tmp_path, monkeypatch):
    project_id = "project"
    memory_id = "mem_20260509_160626_f2734468"
    uploads = tmp_path / project_id / "uploads" / "dream"
    uploads.mkdir(parents=True)
    (uploads / "dream.md").write_text(
        "# Dream Memory\n\n"
        f"<!-- begin syx:memory_id={memory_id} -->\n"
        "## Dream Output: useful memory\n\n"
        "### Syx Metadata\n\n"
        "```yaml\n"
        f"memory_id: {memory_id}\n"
        "entry_type: dream_output\n"
        "```\n\n"
        "full entry body beyond original chunk\n"
        f"<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        entry_expansion,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=25_000),
    )
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id=memory_id,
        artifact_path="dream/dream.md",
        source_document_id=f"dream/dream.md::memory_id={memory_id}",
        result_mode="bounded_entry",
        text="partial body",
    )

    expanded = expand_agent_memory_snippets(project_id=project_id, snippets=[snippet])[0]

    assert expanded.entry_expansion_status == "expanded"
    assert expanded.entry_expansion_method == "artifact_path_boundary"
    assert f"<!-- begin syx:memory_id={memory_id} -->" not in expanded.text
    assert f"<!-- end syx:memory_id={memory_id} -->" not in expanded.text
    assert expanded.text.startswith("## Dream Output: useful memory")
    assert "full entry body beyond original chunk" in expanded.text


def test_unbounded_snippet_gets_not_applicable_status(tmp_path, monkeypatch):
    monkeypatch.setattr(
        entry_expansion,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=25_000),
    )
    snippet = AgentMemorySnippet(snippet_number=1, result_mode="unbounded_chunk_group", text="ordinary upload")

    expanded = expand_agent_memory_snippets(project_id="project", snippets=[snippet])[0]

    assert expanded.entry_expansion_status == "not_applicable"
    assert expanded.entry_expansion_method == "not_applicable"
    assert expanded.text == "ordinary upload"


def test_docstore_reconstruction_is_fallback_and_ordered(tmp_path, monkeypatch):
    project_id = "project"
    source_document_id = "sleep/sleep.md::memory_id=mem_20260509_160626_f2734468"
    faiss_dir = tmp_path / project_id / "faiss"
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "docstore.json").write_text(
        json.dumps(
            {
                "chunk-1": {
                    "text": "second",
                    "metadata": {"source_document_id": source_document_id, "chunk_index": 1},
                },
                "chunk-0": {
                    "text": "first",
                    "metadata": {"source_document_id": source_document_id, "chunk_index": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        entry_expansion,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=25_000),
    )
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id="mem_20260509_160626_f2734468",
        artifact_path="sleep/missing.md",
        source_document_id=source_document_id,
        result_mode="bounded_entry",
        text="original",
    )

    expanded = expand_agent_memory_snippets(project_id=project_id, snippets=[snippet])[0]

    assert expanded.entry_expansion_status == "fallback"
    assert expanded.entry_expansion_method == "docstore_reconstruction"
    assert expanded.entry_expansion_error
    assert expanded.text == "first\nsecond"


def test_artifact_expansion_truncates_without_boundary_markers(tmp_path, monkeypatch):
    project_id = "project"
    memory_id = "mem_20260509_160626_f2734468"
    uploads = tmp_path / project_id / "uploads" / "sleep"
    uploads.mkdir(parents=True)
    (uploads / "sleep.md").write_text(
        f"<!-- begin syx:memory_id={memory_id} -->\n"
        "## Chat Pair: large entry\n\n"
        + ("large body\n" * 300)
        + f"<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        entry_expansion,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=900),
    )
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id=memory_id,
        artifact_path="sleep/sleep.md",
        result_mode="bounded_entry",
        text="partial",
    )

    expanded = expand_agent_memory_snippets(project_id=project_id, snippets=[snippet])[0]

    assert expanded.entry_expansion_status == "expanded_truncated"
    assert expanded.entry_expansion_truncated is True
    assert expanded.entry_expansion_original_chars and expanded.entry_expansion_original_chars > 900
    assert expanded.entry_expansion_returned_chars == len(expanded.text)
    assert expanded.entry_expansion_max_chars == 900
    assert expanded.entry_expansion_truncation_reason == "max_chars_exceeded"
    assert f"<!-- begin syx:memory_id={memory_id} -->" not in expanded.text
    assert f"<!-- end syx:memory_id={memory_id} -->" not in expanded.text
    assert "TRUNCATED" in expanded.text
    assert len(json.dumps(expanded.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True)) <= 900
