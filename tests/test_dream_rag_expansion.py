"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _ensure_module(monkeypatch, name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = []  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_module(monkeypatch, module_name: str, relative_path: str) -> types.ModuleType:
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dream_rag_adapter_uses_route_policy_and_merge(monkeypatch):
    for name in ("app", "app.core", "app.rag", "app.dream"):
        _ensure_module(monkeypatch, name)

    calls = {}

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(base_top_k=6)  # type: ignore[attr-defined]
    config_module.compute_per_source_k = lambda base_top_k, multiplier: int(base_top_k * multiplier)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    class _Query:
        def where(self, *_args, **_kwargs):
            return self

    sqlmodel_module = types.ModuleType("sqlmodel")
    sqlmodel_module.select = lambda *_args, **_kwargs: _Query()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sqlmodel", sqlmodel_module)

    class _ExecResult:
        def first(self):
            return SimpleNamespace(daily_rag_enabled=True)

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def exec(self, *_args, **_kwargs):
            return _ExecResult()

    database_module = types.ModuleType("app.core.database")
    database_module.get_session = lambda: _Session()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.database", database_module)

    class _Project:
        id = "id"

    db_models_module = types.ModuleType("app.core.db_models")
    db_models_module.Project = _Project  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.db_models", db_models_module)

    route_policy_module = types.ModuleType("app.core.route_policy")
    route_policy_module.get_route_policy = lambda route: SimpleNamespace(retrieval_multiplier=2.5, max_keep=24)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.route_policy", route_policy_module)

    manager_module = types.ModuleType("app.rag.manager")

    def merge_daily_and_main(**kwargs):
        calls.update(kwargs)
        return {"context_text": "expanded context", "total_hits": 2, "expanded_unique_chunks_after_merge": 5}

    manager_module.merge_daily_and_main = merge_daily_and_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.rag.manager", manager_module)

    dream_rag = _load_module(monkeypatch, "app.dream.rag", "backend/app/dream/rag.py")

    result = dream_rag.retrieve_dream_context(project_id="project-1", query="memory decay", route="SYNTHESIS")

    assert result["context_text"] == "expanded context"
    assert result["route"] == "SYNTHESIS"
    assert result["per_source_k"] == 15
    assert result["max_keep"] == 24
    assert result["daily_enabled"] is True
    assert calls == {
        "project_id": "project-1",
        "query": "memory decay",
        "daily_enabled": True,
        "max_keep": 24,
        "route": "SYNTHESIS",
        "per_source_k_override": 15,
    }


def test_questions_agent_uses_expanded_dream_rag(monkeypatch):
    for name in ("app", "app.core", "app.dream", "app.dream.agents", "app.dream.agents.prompts", "app.utils"):
        _ensure_module(monkeypatch, name)

    calls = {"rag": [], "prompt": []}

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        dream_enable_remote_research=False,
        dream_max_tokens=128,
        dream_model="model",
        dream_temperature=0.0,
    )
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    llm_module = types.ModuleType("app.core.llm")
    llm_module.generate_text_response = lambda *_args, **_kwargs: SimpleNamespace(text='{"answer": "ok"}', usage={})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.llm", llm_module)

    research_module = types.ModuleType("app.dream.research")
    research_module.count_tokens = lambda text: len(str(text).split())  # type: ignore[attr-defined]
    research_module.trim_to_tokens = lambda text, _max_tokens: text  # type: ignore[attr-defined]
    research_module.fetch_remote_research = lambda _query: ""  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.research", research_module)

    dream_rag_module = types.ModuleType("app.dream.rag")

    def retrieve_dream_context(**kwargs):
        calls["rag"].append(kwargs)
        return {"context_text": "expanded local context"}

    dream_rag_module.retrieve_dream_context = retrieve_dream_context  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.rag", dream_rag_module)

    debug_module = types.ModuleType("app.dream.debug")
    debug_module.safe_dream_purpose = lambda purpose: purpose  # type: ignore[attr-defined]
    debug_module.write_dream_prompt_to_execute = lambda **_kwargs: None  # type: ignore[attr-defined]
    debug_module.write_dream_response_usage_debug = lambda **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.debug", debug_module)

    debug_utils_module = types.ModuleType("app.utils.debug_utils")
    debug_utils_module.write_debug_file = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.debug_utils", debug_utils_module)

    prompts_module = types.ModuleType("app.dream.agents.prompts.questions_prompts")

    def build_answer_question_prompt_local(question, topic, local_context):
        calls["prompt"].append({"question": question, "topic": topic, "local_context": local_context})
        return "prompt"

    prompts_module.build_answer_question_prompt_local = build_answer_question_prompt_local  # type: ignore[attr-defined]
    prompts_module.build_answer_question_prompt_remote = lambda *_args, **_kwargs: "remote prompt"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.agents.prompts.questions_prompts", prompts_module)

    questions_agent = _load_module(
        monkeypatch,
        "app.dream.agents.questions_agent",
        "backend/app/dream/agents/questions_agent.py",
    )

    result = questions_agent._run_open_question_pipeline("project-1", "Can STDP help?", "STDP", "answer_local")

    assert result["answer"] == "ok"
    assert calls["rag"] == [{"project_id": "project-1", "query": "Can STDP help?", "route": "EXPLORATORY"}]
    assert calls["prompt"][0]["local_context"] == "expanded local context"


def test_research_agent_adds_synthesis_expanded_context(monkeypatch):
    for name in ("app", "app.core", "app.dream", "app.dream.agents", "app.dream.agents.prompts", "app.utils"):
        _ensure_module(monkeypatch, name)

    calls = {"rag": [], "prompt": []}

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        dream_max_tokens=128,
        dream_model="model",
        dream_temperature=0.0,
    )
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    llm_module = types.ModuleType("app.core.llm")
    llm_module.generate_text_response = lambda *_args, **_kwargs: SimpleNamespace(text="## Topic\n\n### Key findings\n- fact", usage={})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.llm", llm_module)

    dream_rag_module = types.ModuleType("app.dream.rag")

    def retrieve_dream_context(**kwargs):
        calls["rag"].append(kwargs)
        return {"context_text": "expanded research context"}

    dream_rag_module.retrieve_dream_context = retrieve_dream_context  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.rag", dream_rag_module)

    dream_research_module = types.ModuleType("app.dream.research")
    dream_research_module.count_tokens = lambda text: len(str(text).split())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.research", dream_research_module)

    debug_module = types.ModuleType("app.dream.debug")
    debug_module.safe_dream_purpose = lambda purpose: purpose  # type: ignore[attr-defined]
    debug_module.write_dream_prompt_to_execute = lambda **_kwargs: None  # type: ignore[attr-defined]
    debug_module.write_dream_response_usage_debug = lambda **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.debug", debug_module)

    debug_utils_module = types.ModuleType("app.utils.debug_utils")
    debug_utils_module.write_debug_file = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.debug_utils", debug_utils_module)

    prompts_module = types.ModuleType("app.dream.agents.prompts.research_prompts")

    def build_research_prompt(**kwargs):
        calls["prompt"].append(kwargs)
        return "research prompt"

    prompts_module.build_research_prompt = build_research_prompt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.agents.prompts.research_prompts", prompts_module)

    research_agent = _load_module(
        monkeypatch,
        "app.dream.agents.research_agent",
        "backend/app/dream/agents/research_agent.py",
    )

    result = research_agent.run_research_agent(
        "project-1",
        {
            "items": [
                {
                    "id": "item-1",
                    "origin_text": "origin",
                    "origin_type": "Open Question",
                    "assistant_response": "idea",
                    "source_resolution": "answer_remote",
                    "metadata": {"theme": "memory", "recommended_research": ["topic one"]},
                }
            ]
        },
        "summary",
    )

    assert result["items"][0]["research"][0]["research_topic"] == "topic one"
    assert calls["rag"] == [{"project_id": "project-1", "query": "topic one", "route": "SYNTHESIS"}]
    assert calls["prompt"][0]["local_context_text"] == "expanded research context"


def test_dream_context_topic_enrichment_uses_expanded_adapter(monkeypatch):
    for name in ("app", "app.core", "app.dream", "app.utils"):
        _ensure_module(monkeypatch, name)

    calls = []

    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: SimpleNamespace(memory_root="")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)

    llm_module = types.ModuleType("app.core.llm")
    llm_module.generate_text_response = lambda *_args, **_kwargs: SimpleNamespace(text="", usage={})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.llm", llm_module)

    tokens_module = types.ModuleType("app.utils.tokens")
    tokens_module.count_tokens = lambda text: len(str(text).split())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.tokens", tokens_module)

    debug_module = types.ModuleType("app.dream.debug")
    debug_module.safe_dream_purpose = lambda purpose: purpose  # type: ignore[attr-defined]
    debug_module.write_dream_prompt_to_execute = lambda **_kwargs: None  # type: ignore[attr-defined]
    debug_module.write_dream_response_usage_debug = lambda **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.debug", debug_module)

    prompts_module = types.ModuleType("app.dream.prompts")
    prompts_module.build_project_summary_prompt = lambda text: text  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.prompts", prompts_module)

    dream_rag_module = types.ModuleType("app.dream.rag")

    def retrieve_dream_context(**kwargs):
        calls.append(kwargs)
        return {
            "context_text": "Context:\n---\nSnippet 1\nexpanded topic context",
            "total_hits": 1,
            "expanded_unique_chunks_after_merge": 3,
            "route": kwargs["route"],
            "per_source_k": 12,
            "max_keep": 20,
            "daily_enabled": True,
        }

    dream_rag_module.retrieve_dream_context = retrieve_dream_context  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.dream.rag", dream_rag_module)

    debug_utils_module = types.ModuleType("app.utils.debug_utils")
    debug_utils_module.write_debug_file = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.utils.debug_utils", debug_utils_module)

    context_module = _load_module(monkeypatch, "app.dream.context", "backend/app/dream/context.py")
    monkeypatch.setattr(context_module, "_extract_rag_topics", lambda _project_id: ["topic one"])

    context_text = context_module._build_project_rag_context("project-1")

    assert calls == [{"project_id": "project-1", "query": "topic one", "route": "EXPLORATORY"}]
    assert "expanded topic context" in context_text
