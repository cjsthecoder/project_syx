"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.agents.questions_agent.

The consolidation artifact is written under a temp memory root; the retrieval,
remote-research, and LLM boundaries plus debug writers are faked so nothing
reaches FAISS, the network, or a model.
"""

import json
import os
from types import SimpleNamespace

from app.dream.agents import questions_agent


def _settings(enable_remote=True):
    return SimpleNamespace(
        memory_root="/unused",  # overridden per-test via monkeypatch where needed
        dream_max_tokens=128,
        dream_model="dream-mini",
        dream_temperature=0.7,
        dream_enable_remote_research=enable_remote,
        dream_remote_context_max_tokens=200,
    )


def _patch_pipeline(
    monkeypatch,
    *,
    enable_remote=True,
    llm_text='{"answer": "the answer"}',
    retrieve_raises=False,
    llm_raises=False,
    remote_text="remote research blob",
):
    monkeypatch.setattr(questions_agent, "get_settings", lambda: _settings(enable_remote))
    monkeypatch.setattr(questions_agent, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(questions_agent, "write_dream_prompt_to_execute", lambda **k: None)
    monkeypatch.setattr(questions_agent, "write_dream_response_usage_debug", lambda **k: None)

    def _retrieve(**k):
        if retrieve_raises:
            raise RuntimeError("retrieval boom")
        return {"context_text": "local ctx"}

    monkeypatch.setattr(questions_agent, "retrieve_dream_context", _retrieve)
    monkeypatch.setattr(questions_agent, "fetch_remote_research", lambda q: remote_text)

    def _gen(*a, **k):
        if llm_raises:
            raise RuntimeError("llm down")
        return SimpleNamespace(text=llm_text, usage=SimpleNamespace())

    monkeypatch.setattr(questions_agent, "generate_text_response", _gen)


# --- _load_consolidated_questions -----------------------------------------


def test_load_consolidated_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    assert questions_agent._load_consolidated_questions("p1") == {"questions": []}


def _write_consolidated(tmp_path, project_id, payload):
    base = os.path.join(str(tmp_path), project_id)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "open_questions_consolidated.json")
    with open(path, "w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle)


def test_load_consolidated_happy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", {"questions": [{"question": "Q?"}]})
    out = questions_agent._load_consolidated_questions("p1")
    assert out["questions"] == [{"question": "Q?"}]


def test_load_consolidated_non_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", "[1, 2, 3]")
    assert questions_agent._load_consolidated_questions("p1") == {"questions": []}


def test_load_consolidated_questions_not_list(monkeypatch, tmp_path):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", {"questions": "nope"})
    assert questions_agent._load_consolidated_questions("p1") == {"questions": []}


def test_load_consolidated_read_error(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", "{not valid json")
    assert questions_agent._load_consolidated_questions("p1") == {"questions": []}
    assert any("failed reading" in r.message for r in caplog.records)


# --- _run_open_question_pipeline ------------------------------------------


def test_pipeline_local_only(monkeypatch):
    _patch_pipeline(monkeypatch)
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_local")
    assert out["answer"] == "the answer"
    assert out["used_remote_research"] is False


def test_pipeline_remote_research_used(monkeypatch):
    _patch_pipeline(monkeypatch, enable_remote=True)
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_remote")
    assert out["used_remote_research"] is True


def test_pipeline_remote_research_trimmed(monkeypatch, caplog):
    # Cap remote context very low so trim_to_tokens shrinks it -> trim warning.
    monkeypatch.setattr(
        questions_agent,
        "get_settings",
        lambda: SimpleNamespace(
            memory_root="/unused",
            dream_max_tokens=128,
            dream_model="dream-mini",
            dream_temperature=0.7,
            dream_enable_remote_research=True,
            dream_remote_context_max_tokens=2,
        ),
    )
    monkeypatch.setattr(questions_agent, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(questions_agent, "write_dream_prompt_to_execute", lambda **k: None)
    monkeypatch.setattr(questions_agent, "write_dream_response_usage_debug", lambda **k: None)
    monkeypatch.setattr(
        questions_agent, "retrieve_dream_context", lambda **k: {"context_text": "c"}
    )
    monkeypatch.setattr(
        questions_agent,
        "fetch_remote_research",
        lambda q: "a long remote research blob with many tokens",
    )
    monkeypatch.setattr(
        questions_agent,
        "generate_text_response",
        lambda *a, **k: SimpleNamespace(text='{"answer": "ok"}', usage=SimpleNamespace()),
    )
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_remote")
    assert out["used_remote_research"] is True
    assert any("trimmed remote" in r.message for r in caplog.records)


def test_pipeline_remote_empty_research(monkeypatch):
    _patch_pipeline(monkeypatch, enable_remote=True, remote_text="")
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_remote")
    assert out["used_remote_research"] is False


def test_pipeline_retrieval_failure_degrades(monkeypatch):
    _patch_pipeline(monkeypatch, retrieve_raises=True)
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_local")
    assert out["answer"] == "the answer"


def test_pipeline_llm_failure_placeholder(monkeypatch):
    _patch_pipeline(monkeypatch, llm_raises=True)
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_local")
    assert "failed to generate" in out["answer"]


def test_pipeline_invalid_json_shape(monkeypatch):
    _patch_pipeline(monkeypatch, llm_text='{"not_answer": 1}')
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_local")
    assert "failed to generate" in out["answer"]


def test_pipeline_invalid_json(monkeypatch):
    _patch_pipeline(monkeypatch, llm_text="not json")
    out = questions_agent._run_open_question_pipeline("p1", "Q?", "topic", "answer_local")
    assert "failed to generate" in out["answer"]


# --- run_questions_agent ---------------------------------------------------


def test_run_questions_agent_processes_questions(monkeypatch, tmp_path):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(
        tmp_path,
        "p1",
        {
            "questions": [
                {"question": "Q1?", "topic": "t", "resolution": "answer_local"},
                {"question": "", "topic": "t"},  # skipped (no question)
            ]
        },
    )
    # Patch the per-question pipeline so we don't re-test it here.
    monkeypatch.setattr(
        questions_agent,
        "_run_open_question_pipeline",
        lambda pid, q, topic, res: {
            "question": q,
            "topic": topic,
            "resolution": res,
            "answer": "A",
            "used_remote_research": False,
        },
    )
    monkeypatch.setattr(questions_agent, "write_debug_file", lambda *a, **k: None)
    out = questions_agent.run_questions_agent("p1")
    assert len(out["questions"]) == 1
    assert out["questions"][0]["answer"] == "A"


def test_run_questions_agent_per_question_error_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", {"questions": [{"question": "Q1?"}]})
    monkeypatch.setattr(
        questions_agent,
        "_run_open_question_pipeline",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pipeline boom")),
    )
    monkeypatch.setattr(questions_agent, "write_debug_file", lambda *a, **k: None)
    out = questions_agent.run_questions_agent("p1")
    assert out["questions"] == []
    assert any("per-question pipeline error" in r.message for r in caplog.records)


def test_run_questions_agent_debug_write_failure_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        questions_agent, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path))
    )
    _write_consolidated(tmp_path, "p1", {"questions": []})
    monkeypatch.setattr(
        questions_agent, "write_debug_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    )
    out = questions_agent.run_questions_agent("p1")
    assert out["questions"] == []
    assert any("failed writing debug_questions" in r.message for r in caplog.records)


def test_run_questions_agent_non_list_questions_normalized(monkeypatch):
    # _load returns a dict whose "questions" is not a list -> normalized to [].
    monkeypatch.setattr(
        questions_agent, "_load_consolidated_questions", lambda pid: {"questions": "not-a-list"}
    )
    monkeypatch.setattr(questions_agent, "write_debug_file", lambda *a, **k: None)
    out = questions_agent.run_questions_agent("p1")
    assert out == {"questions": []}


def test_run_questions_agent_outer_failure_returns_empty(monkeypatch, caplog):
    monkeypatch.setattr(
        questions_agent,
        "_load_consolidated_questions",
        lambda pid: (_ for _ in ()).throw(RuntimeError("load boom")),
    )
    out = questions_agent.run_questions_agent("p1")
    assert out == {"questions": []}
