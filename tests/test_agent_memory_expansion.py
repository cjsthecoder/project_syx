"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for agent memory snippet entry expansion.

Covers ``expand_agent_memory_snippets``: expanding bounded snippets from the
artifact file, marking unbounded snippets not-applicable, deduplicating
repeated memory ids, falling back to docstore reconstruction, and truncating
oversized entries to the configured character limit.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _install_stub_if_missing(name: str, stub: types.ModuleType) -> None:
    """Register a lightweight stub only when the real package is not installed.

    Crucially, when the real package IS installed we leave sys.modules untouched:
    permanently swapping in a stub here would leak into every later test module
    in a full-suite run (e.g. shadowing ``numpy.linalg`` used by RAG retrieval).

    Args:
        name: Top-level module name to guard (e.g. ``"numpy"``).
        stub: Lightweight stand-in to install only when the real one is absent.
    """
    cached = sys.modules.get(name)
    if cached is not None and getattr(cached, "__spec__", None) is not None:
        return  # real module already imported; use it
    sys.modules.pop(name, None)
    try:
        available = importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        available = False
    if available:
        return  # leave unset so the real package imports on next use
    sys.modules[name] = stub


numpy_module = types.ModuleType("numpy")
numpy_module.ndarray = object  # type: ignore[attr-defined]
_install_stub_if_missing("numpy", numpy_module)

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
    snippet = AgentMemorySnippet(
        snippet_number=1, result_mode="unbounded_chunk_group", text="ordinary upload"
    )

    expanded = expand_agent_memory_snippets(project_id="project", snippets=[snippet])[0]

    assert expanded.entry_expansion_status == "not_applicable"
    assert expanded.entry_expansion_method == "not_applicable"
    assert expanded.text == "ordinary upload"


def test_duplicate_bounded_memory_ids_expand_once(tmp_path, monkeypatch):
    project_id = "project"
    memory_id = "mem_20260509_160626_f2734468"
    uploads = tmp_path / project_id / "uploads" / "sleep"
    uploads.mkdir(parents=True)
    (uploads / "sleep.md").write_text(
        f"<!-- begin syx:memory_id={memory_id} -->\n"
        "## Chat Pair: deduped entry\n\n"
        "shared body\n"
        f"<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        entry_expansion,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=25_000),
    )
    snippets = [
        AgentMemorySnippet(
            snippet_number=1,
            memory_id=memory_id,
            artifact_path="sleep/sleep.md",
            source_document_id=f"sleep/sleep.md::memory_id={memory_id}",
            result_mode="bounded_entry",
            text="first partial chunk",
        ),
        AgentMemorySnippet(
            snippet_number=2,
            memory_id=memory_id,
            artifact_path="sleep/sleep.md",
            source_document_id=f"sleep/sleep.md::memory_id={memory_id}",
            result_mode="bounded_entry",
            text="second partial chunk",
        ),
    ]

    expanded = expand_agent_memory_snippets(project_id=project_id, snippets=snippets)

    assert len(expanded) == 1
    assert expanded[0].snippet_number == 1
    assert expanded[0].entry_expansion_status == "expanded"
    assert "shared body" in expanded[0].text


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
    assert (
        len(json.dumps(expanded.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True))
        <= 900
    )


def _settings(tmp_path, max_chars=25_000):
    return SimpleNamespace(memory_root=str(tmp_path), agent_memory_max_entry_chars=max_chars)


def test_invalid_max_chars_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    snippet = AgentMemorySnippet(snippet_number=1, result_mode="unbounded_chunk_group", text="x")
    # A non-numeric override hits the int() guard and falls back internally.
    out = expand_agent_memory_snippets(
        project_id="p", snippets=[snippet], max_serialized_chars="bad"
    )[0]
    assert out.entry_expansion_status == "not_applicable"


def test_expand_via_source_document_id_when_artifact_path_absent(tmp_path, monkeypatch):
    project_id = "project"
    memory_id = "mem_20260509_160626_f2734468"
    uploads = tmp_path / project_id / "uploads" / "sleep"
    uploads.mkdir(parents=True)
    (uploads / "sleep.md").write_text(
        f"<!-- begin syx:memory_id={memory_id} -->\n"
        "## Chat Pair: via sdid\n\n"
        "sdid body\n"
        f"<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id=memory_id,
        artifact_path=None,  # forces source_document_id boundary path
        source_document_id=f"sleep/sleep.md::memory_id={memory_id}",
        result_mode="bounded_entry",
        text="partial",
    )
    out = expand_agent_memory_snippets(project_id=project_id, snippets=[snippet])[0]
    assert out.entry_expansion_status == "expanded"
    assert out.entry_expansion_method == "source_document_id_boundary"
    assert "sdid body" in out.text


def test_fallback_to_original_snippet_when_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id="mem_x",
        artifact_path=None,
        source_document_id=None,
        result_mode="bounded_entry",
        text="only the original chunk",
    )
    out = expand_agent_memory_snippets(project_id="project", snippets=[snippet])[0]
    assert out.entry_expansion_status == "fallback"
    assert out.entry_expansion_method == "original_snippet"
    assert out.text == "only the original chunk"


def test_failed_when_no_text_and_no_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    snippet = AgentMemorySnippet(
        snippet_number=1,
        memory_id="mem_x",
        artifact_path=None,
        source_document_id=None,
        result_mode="bounded_entry",
        text="",
    )
    out = expand_agent_memory_snippets(project_id="project", snippets=[snippet])[0]
    assert out.entry_expansion_status == "failed"
    assert out.entry_expansion_error


# --- _extract_from_artifact ------------------------------------------------


def test_extract_from_artifact_rejects_escape_path(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    text, error = entry_expansion._extract_from_artifact("project", "../../etc/passwd", "mem_x", 1)
    assert text is None and error == "unsafe_artifact_path"


def test_extract_from_artifact_read_failure(tmp_path, monkeypatch):
    (tmp_path / "project" / "uploads").mkdir(parents=True)
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    text, error = entry_expansion._extract_from_artifact("project", "missing.md", "mem_x", 1)
    assert text is None and error == "artifact_read_failed"


def test_extract_from_artifact_memory_id_not_found(tmp_path, monkeypatch):
    uploads = tmp_path / "project" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.md").write_text(
        "<!-- begin syx:memory_id=other -->\nbody\n<!-- end syx:memory_id=other -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    text, error = entry_expansion._extract_from_artifact("project", "a.md", "mem_x", 1)
    assert text is None and error == "memory_id_boundary_not_found"


def test_extract_from_artifact_duplicate_boundary_warning(tmp_path, monkeypatch, caplog):
    memory_id = "mem_20260509_160626_f2734468"
    uploads = tmp_path / "project" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "dup.md").write_text(
        f"<!-- begin syx:memory_id={memory_id} -->\nfirst body\n<!-- end syx:memory_id={memory_id} -->\n"
        f"<!-- begin syx:memory_id={memory_id} -->\nsecond body\n<!-- end syx:memory_id={memory_id} -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    text, error = entry_expansion._extract_from_artifact("project", "dup.md", memory_id, 1)
    # Parser dedupes (keeps the first), but logs the duplicate-boundary warning.
    assert text == "first body" and error is None
    assert any("duplicate memory_id boundaries" in r.message for r in caplog.records)


def test_extract_from_artifact_multiple_matches_logs(tmp_path, monkeypatch, caplog):
    # Fake the parser to return two entries with the same memory_id to exercise
    # the defensive len(matches) > 1 logging branch.
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    uploads = tmp_path / "project" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.md").write_text("anything", encoding="utf-8")

    fake_result = SimpleNamespace(
        warnings=[],
        entries=[
            SimpleNamespace(memory_id="mem_x", text="  first  "),
            SimpleNamespace(memory_id="mem_x", text="second"),
        ],
    )
    monkeypatch.setattr(entry_expansion, "parse_syx_entries", lambda *a, **k: fake_result)
    text, error = entry_expansion._extract_from_artifact("project", "a.md", "mem_x", 1)
    assert text == "first" and error is None  # first match, stripped
    assert any(
        "duplicate memory_id boundaries" in r.message and "count" in r.message
        for r in caplog.records
    )


# --- _reconstruct_from_docstore -------------------------------------------


def test_reconstruct_no_source_document_id_returns_empty():
    assert entry_expansion._reconstruct_from_docstore(project_id="p", source_document_id=None) == ""


def test_reconstruct_docstore_not_dict_returns_empty(tmp_path, monkeypatch):
    faiss_dir = tmp_path / "p" / "faiss"
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "docstore.json").write_text("[]", encoding="utf-8")  # not a dict
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    assert entry_expansion._reconstruct_from_docstore(project_id="p", source_document_id="x") == ""


def test_reconstruct_skips_bad_entries(tmp_path, monkeypatch):
    sdid = "sleep/sleep.md::memory_id=m1"
    faiss_dir = tmp_path / "p" / "faiss"
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "docstore.json").write_text(
        json.dumps(
            {
                "non_dict": "skip me",
                "wrong_doc": {"text": "no", "metadata": {"source_document_id": "other"}},
                "bad_index": {
                    "text": "no",
                    "metadata": {"source_document_id": sdid, "chunk_index": "x", "chunk_seq": None},
                },
                "ok1": {
                    "text": "second",
                    "metadata": {"source_document_id": sdid, "chunk_index": 1},
                },
                "ok0": {
                    "text": "first",
                    "metadata": {"source_document_id": sdid, "chunk_index": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    out = entry_expansion._reconstruct_from_docstore(project_id="p", source_document_id=sdid)
    assert out == "first\nsecond"  # ordered by chunk_index; bad entries skipped


def test_reconstruct_no_matching_chunks_returns_empty(tmp_path, monkeypatch):
    sdid = "sleep/sleep.md::memory_id=m1"
    faiss_dir = tmp_path / "p" / "faiss"
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "docstore.json").write_text(
        json.dumps(
            {
                "bad_index": {
                    "text": "x",
                    "metadata": {"source_document_id": sdid, "chunk_index": "x", "chunk_seq": "y"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_expansion, "get_settings", lambda: _settings(tmp_path))
    assert entry_expansion._reconstruct_from_docstore(project_id="p", source_document_id=sdid) == ""


# --- _clean_upload_relative_path / _is_within -----------------------------


def test_clean_upload_relative_path_rejects_unsafe(caplog):
    assert (
        entry_expansion._clean_upload_relative_path(
            "../escape", project_id="p", memory_id="m", snippet_number=1, field="artifact_path"
        )
        is None
    )
    assert (
        entry_expansion._clean_upload_relative_path(
            "/abs/path", project_id="p", memory_id="m", snippet_number=1, field="artifact_path"
        )
        is None
    )
    assert any("rejected unsafe upload-relative path" in r.message for r in caplog.records)


def test_clean_upload_relative_path_normalizes_backslashes():
    out = entry_expansion._clean_upload_relative_path(
        "sub\\file.md", project_id="p", memory_id="m", snippet_number=1, field="artifact_path"
    )
    assert out == "sub/file.md"


def test_is_within_handles_value_error(monkeypatch):
    def boom(_paths):
        raise ValueError("different drives")

    monkeypatch.setattr(entry_expansion.os.path, "commonpath", boom)
    assert entry_expansion._is_within("/a/b", "/a") is False
