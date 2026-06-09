"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the agent memory search interface.

Covers parsing of prompt context into structured snippets, the
``/agent/memory/search`` endpoint behavior (auth, sleep lock, structured
responses), and the ``agent_memory_search`` CLI output and debug files.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_stub_if_missing(name: str, stub: types.ModuleType) -> None:
    """Register a lightweight stub only when the real package is not installed.

    When the real package IS installed we leave sys.modules untouched: permanently
    swapping in a stub here would leak into every later test module in a full-suite
    run (e.g. shadowing ``faiss.IndexFlatIP``).

    Args:
        name: Top-level module name to guard (e.g. ``"faiss"``).
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


faiss_module = types.ModuleType("faiss")
faiss_module.IndexFlatIP = type("IndexFlatIP", (), {})  # type: ignore[attr-defined]
faiss_module.read_index = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
_install_stub_if_missing("faiss", faiss_module)

numpy_module = types.ModuleType("numpy")
numpy_module.ndarray = object  # type: ignore[attr-defined]
numpy_module.float32 = "float32"  # type: ignore[attr-defined]
numpy_module.array = lambda value, dtype=None: value  # type: ignore[attr-defined]
_install_stub_if_missing("numpy", numpy_module)

embedding_factory_module = types.ModuleType("app.embedding.factory")
embedding_factory_module.get_embedding_client = lambda: None  # type: ignore[attr-defined]
sys.modules.setdefault("app.embedding.factory", embedding_factory_module)

from app.agent_interface.models import AgentMemorySearchResponse, AgentMemorySnippet
from app.agent_interface.parser import parse_prompt_context_to_snippets
from app.agent_interface.router import router

from tools import agent_memory_search

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_parse_prompt_context_to_structured_snippets():
    context = (
        "Context:\n---\n"
        "Snippet 1 (source=ltm, cos=0.6411, score=0.8206, file=sleep.md, page=None, chunk_index=0..1)\n"
        "### Syx Metadata\n\n"
        "```yaml\n"
        "memory_id: mem_20260507_160709_1aebd6c4\n"
        "entry_type: dream_output\n"
        "source_agent: syx\n"
        "source_scope: daily\n"
        "current_scope: dream\n"
        "semantic_handle: useful memory attribution\n"
        "topics:\n"
        "  - retrieval\n"
        "  - attribution\n"
        "artifact_path: dream/dream.md\n"
        "```\n\n"
        "retrieved body\n"
    )

    snippets = parse_prompt_context_to_snippets(context)

    assert len(snippets) == 1
    snippet = snippets[0]
    assert snippet.snippet_number == 1
    assert snippet.source == "ltm"
    assert snippet.score == 0.8206
    assert snippet.cos == 0.6411
    assert snippet.file == "sleep.md"
    assert snippet.page is None
    assert snippet.chunk_index_start == 0
    assert snippet.chunk_index_end == 1
    assert snippet.chunk_index_range == "0..1"
    assert snippet.memory_id == "mem_20260507_160709_1aebd6c4"
    assert snippet.source_document_id == "dream/dream.md::memory_id=mem_20260507_160709_1aebd6c4"
    assert snippet.entry_type == "dream_output"
    assert snippet.semantic_handle == "useful memory attribution"
    assert snippet.topics == ["retrieval", "attribution"]
    assert snippet.result_mode == "bounded_entry"
    assert "Snippet 1" not in snippet.text
    assert "```yaml" in snippet.text


def test_parse_prompt_context_ignores_internal_markdown_separators():
    context = (
        "Context:\n---\n"
        "Snippet 1 (source=ltm, cos=0.7000, score=0.8500, file=a.md, page=None, chunk_index=0..2)\n"
        "first body\n\n"
        "---\n"
        "### Internal section\n"
        "still snippet one\n\n"
        "---\n"
        "Snippet 2 (source=ltm, cos=0.6000, score=0.8000, file=b.md, page=None, chunk_index=3)\n"
        "second body\n"
    )

    snippets = parse_prompt_context_to_snippets(context)

    assert len(snippets) == 2
    assert snippets[0].snippet_number == 1
    assert "### Internal section" in snippets[0].text
    assert "still snippet one" in snippets[0].text
    assert snippets[1].snippet_number == 2
    assert snippets[1].chunk_index_start == 3
    assert snippets[1].chunk_index_end == 3


def test_parse_prompt_context_ignores_embedded_historical_snippet_headers():
    context = (
        "Context:\n---\n"
        "Snippet 1 (source=ltm, cos=0.7000, score=0.8500, file=a.md, page=None, chunk_index=0..2)\n"
        "current retrieved body\n\n"
        "Historical output included inside the memory:\n"
        "Snippet 1 (source=ltm, score=0.84, file=old.txt, page=None)\n"
        "old nested body that should remain text\n\n"
        "---\n"
        "Snippet 2 (source=ltm, cos=0.6000, score=0.8000, file=b.md, page=None, chunk_index=3)\n"
        "second current retrieved body\n"
    )

    snippets = parse_prompt_context_to_snippets(context)

    assert len(snippets) == 2
    assert snippets[0].snippet_number == 1
    assert "Historical output included inside the memory" in snippets[0].text
    assert "Snippet 1 (source=ltm, score=0.84, file=old.txt, page=None)" in snippets[0].text
    assert "old nested body that should remain text" in snippets[0].text
    assert snippets[1].snippet_number == 2


def test_parse_prompt_context_uses_header_syx_metadata_for_mid_entry_chunks():
    memory_id = "mem_20260507_183158_8c23347a"
    source_document_id = f"sleep/sleep.md::memory_id={memory_id}"
    context = (
        "Context:\n---\n"
        "Snippet 1 (source=ltm, cos=0.7691, score=0.8846, file=sleep.md, page=None, "
        f"chunk_index=4..10, memory_id={memory_id}, source_document_id={source_document_id}, "
        "artifact_path=sleep/sleep.md, entry_type=chat_pair, source_scope=daily, current_scope=ltm)\n"
        "mid-entry chunk text without a YAML metadata block\n"
    )

    snippets = parse_prompt_context_to_snippets(context)

    assert len(snippets) == 1
    snippet = snippets[0]
    assert snippet.result_mode == "bounded_entry"
    assert snippet.memory_id == memory_id
    assert snippet.source_document_id == source_document_id
    assert snippet.artifact_path == "sleep/sleep.md"
    assert snippet.entry_type == "chat_pair"
    assert snippet.source_scope == "daily"
    assert snippet.current_scope == "ltm"


def test_agent_memory_search_endpoint_returns_structured_snippets(monkeypatch):
    calls = {}

    def fake_retrieve(**kwargs):
        calls.update(kwargs)
        response = AgentMemorySearchResponse(
            project_name=kwargs["project_name"],
            project_id=kwargs["project_id"],
            category=kwargs["category"],
            query=kwargs["query"],
            model=kwargs["model"],
            snippet_count=1,
            bounded_result_count=1,
            unbounded_result_count=0,
            snippets=[
                AgentMemorySnippet(
                    snippet_number=1,
                    source="ltm",
                    score=0.9,
                    cos=0.8,
                    memory_id="mem_1",
                    result_mode="bounded_entry",
                    text="body",
                )
            ],
        )
        return response, "Context:\n---\nSnippet 1 (...)\nbody", []

    monkeypatch.setattr(
        "app.agent_interface.router.resolve_project_name",
        lambda _name: SimpleNamespace(id="proj-1"),
    )
    monkeypatch.setattr("app.agent_interface.router.is_sleeping", lambda: False)
    monkeypatch.setattr("app.agent_interface.router.retrieve_agent_memory", fake_retrieve)
    monkeypatch.setattr(
        "app.agent_interface.router.write_agent_debug_files", lambda **_kwargs: None
    )

    with patch(
        "app.core.query_builder.build_query", side_effect=AssertionError("classifier called")
    ):
        with patch(
            "app.core.llm_service.generate_chat_response",
            side_effect=AssertionError("model called"),
        ):
            response = client.post(
                "/agent/memory/search",
                json={
                    "project_name": "Project_Syx",
                    "query": "requirements",
                    "category": "unknown",
                    "model": "not-a-whitelisted-model",
                    "agent_token": "",
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["project_name"] == "Project_Syx"
    assert body["project_id"] == "proj-1"
    assert body["category"] == "OTHER"
    assert body["model"] == "not-a-whitelisted-model"
    assert body["snippet_count"] == 1
    assert body["snippets"][0]["memory_id"] == "mem_1"
    assert "content" not in body
    assert calls["category"] == "OTHER"


def test_agent_memory_search_missing_token_returns_401():
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "Project_Syx", "query": "requirements"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "Missing agent token."}


def test_agent_memory_search_sleep_lock_reaches_endpoint(monkeypatch):
    monkeypatch.setattr("app.agent_interface.router.is_sleeping", lambda: True)
    monkeypatch.setattr(
        "app.agent_interface.router.resolve_project_name",
        lambda _name: SimpleNamespace(id="proj-1"),
    )

    response = client.post(
        "/agent/memory/search",
        json={"project_name": "Project_Syx", "query": "requirements", "agent_token": ""},
    )

    assert response.status_code == 423
    assert response.json()["error"] == "memory_locked"
    assert response.json()["project_id"] == "proj-1"


def _authz(authorized=True, forbidden=False, message=None):
    return SimpleNamespace(authorized=authorized, forbidden=forbidden, message=message)


def test_agent_memory_search_missing_project_name_returns_400():
    response = client.post("/agent/memory/search", json={"query": "q", "agent_token": ""})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_agent_memory_search_missing_query_returns_400():
    response = client.post("/agent/memory/search", json={"project_name": "P", "agent_token": ""})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_agent_memory_search_project_not_found_returns_404(monkeypatch):
    monkeypatch.setattr("app.agent_interface.router.resolve_project_name", lambda _n: None)
    response = client.post(
        "/agent/memory/search", json={"project_name": "Ghost", "query": "q", "agent_token": ""}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "project_not_found"
    assert response.json()["project_name"] == "Ghost"


def test_agent_memory_search_forbidden_returns_403(monkeypatch):
    monkeypatch.setattr(
        "app.agent_interface.router.resolve_project_name",
        lambda _n: SimpleNamespace(id="proj-1"),
    )
    monkeypatch.setattr(
        "app.agent_interface.router.authorize_agent_token",
        lambda _pid, _tok: _authz(authorized=False, forbidden=True, message="denied"),
    )
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "P", "query": "q", "agent_token": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert response.json()["message"] == "denied"


def test_agent_memory_search_unauthorized_returns_401(monkeypatch):
    monkeypatch.setattr(
        "app.agent_interface.router.resolve_project_name",
        lambda _n: SimpleNamespace(id="proj-1"),
    )
    monkeypatch.setattr(
        "app.agent_interface.router.authorize_agent_token",
        lambda _pid, _tok: _authz(authorized=False, forbidden=False, message="bad token"),
    )
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "P", "query": "q", "agent_token": "bad"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert response.json()["message"] == "bad token"


def _setup_authorized(monkeypatch):
    monkeypatch.setattr(
        "app.agent_interface.router.resolve_project_name",
        lambda _n: SimpleNamespace(id="proj-1"),
    )
    monkeypatch.setattr(
        "app.agent_interface.router.authorize_agent_token", lambda _pid, _tok: _authz()
    )
    monkeypatch.setattr("app.agent_interface.router.is_sleeping", lambda: False)


def test_agent_memory_search_snippet_parse_error_returns_500(monkeypatch):
    from app.agent_interface.parser import SnippetParseError

    _setup_authorized(monkeypatch)
    debug_calls = []

    def boom(**_kwargs):
        raise SnippetParseError("unparseable", raw_context="raw ctx")

    monkeypatch.setattr("app.agent_interface.router.retrieve_agent_memory", boom)
    monkeypatch.setattr(
        "app.agent_interface.router.write_agent_debug_files",
        lambda **kwargs: debug_calls.append(kwargs),
    )
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "P", "query": "q", "agent_token": ""},
    )
    assert response.status_code == 500
    assert response.json()["error"] == "snippet_parse_failed"
    # Debug artifacts are still written on the parse-failure path.
    assert debug_calls and debug_calls[0]["error_payload"]["error"] == "snippet_parse_failed"


def test_agent_memory_search_generic_error_returns_500(monkeypatch):
    _setup_authorized(monkeypatch)
    monkeypatch.setattr(
        "app.agent_interface.router.retrieve_agent_memory",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    response = client.post(
        "/agent/memory/search",
        json={"project_name": "P", "query": "q", "agent_token": ""},
    )
    assert response.status_code == 500
    assert response.json()["error"] == "agent_memory_search_failed"


def test_cli_prints_raw_json_and_writes_debug(tmp_path, monkeypatch, capsys):
    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return json.dumps(
                {
                    "project_name": "Project_Syx",
                    "project_id": "proj-1",
                    "category": "OTHER",
                    "query": "requirements",
                    "snippet_count": 0,
                    "bounded_result_count": 0,
                    "unbounded_result_count": 0,
                    "snippets": [],
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        agent_memory_search.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response()
    )

    rc = agent_memory_search.main(
        [
            "--project-name",
            "Project_Syx",
            "--query",
            "requirements",
            "--agent-token",
            "",
            "--debug-dir",
            str(tmp_path),
        ]
    )

    assert rc == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["snippets"] == []
    debug_files = list(tmp_path.glob("agent_memory_search_*.json"))
    assert len(debug_files) == 1
    debug_payload = json.loads(debug_files[0].read_text(encoding="utf-8"))
    assert debug_payload["response_json"]["project_id"] == "proj-1"
    assert "prompt_shaped_text" not in debug_payload
    assert "entry_expansion_summary" in debug_payload
