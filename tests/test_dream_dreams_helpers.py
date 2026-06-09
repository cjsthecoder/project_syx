"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.dreams helper functions and stage orchestration edges.

These target the pure helpers (fuzzy matching, JSON read, debug row builders,
resolution/bridge helpers) and the failure branches of the research stage and
the top-level dream() orchestrator. Agent/IO boundaries are faked so nothing
reaches a model, FAISS, or the network.
"""

import json
from types import SimpleNamespace

from app.dream import dreams

# --- pure helpers ----------------------------------------------------------


def test_question_key_equivalent_branches():
    assert dreams._question_key_equivalent("", "x") is False  # empty key
    assert dreams._question_key_equivalent("Same Text!", "same text") is True  # exact normalized
    long = "this is a sufficiently long question about budgets"
    assert dreams._question_key_equivalent(long, "budgets") is True  # container >= 24 chars
    assert dreams._question_key_equivalent("budgets", long) is True  # reversed containment
    assert dreams._question_key_equivalent("alpha", "beta") is False  # no relation


def test_read_json_file_safe(tmp_path):
    assert dreams._read_json_file_safe(str(tmp_path / "missing.json")) is None
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"k": 1}), encoding="utf-8")
    assert dreams._read_json_file_safe(str(good)) == {"k": 1}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert dreams._read_json_file_safe(str(bad)) is None


def test_safe_write_dreaming_debug_swallows_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        dreams, "_write_dreaming_debug_txt", lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    )
    dreams._safe_write_dreaming_debug("p1", "ts", "suffix", [("T", "C")])
    assert any("Failed writing suffix debug" in r.message for r in caplog.records)


def test_write_dreaming_debug_txt_invokes_writer(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        dreams,
        "write_debug_file",
        lambda pid, path, body: captured.update(pid=pid, path=path, body=body),
    )
    dreams._write_dreaming_debug_txt("p1", "ts", "questions_out", [("INPUT", "hello")])
    assert "questions_out" in captured["path"] and "INPUT" in captured["body"]


def test_build_research_plan_rows():
    assert dreams._build_research_plan_rows({"items": "not-a-list"}) == []
    data = {
        "items": [
            "not-a-dict",
            {
                "id": "i1",
                "origin_text": "o",
                "metadata": {"theme": "t", "recommended_research": ["topicA", "  "]},
            },
        ]
    }
    rows = dreams._build_research_plan_rows(data)
    assert rows == [{"item_id": "i1", "origin_text": "o", "theme": "t", "research_topic": "topicA"}]


def test_extract_question_resolution_rows():
    assert dreams._extract_question_resolution_rows({"questions": "nope"}) == []
    data = {
        "questions": [
            "not-a-dict",
            {"question": "", "resolution": "answer_local"},  # empty question skipped
            {"question": "Q?", "resolution": "bogus"},  # unknown resolution skipped
            {"question": "Q2?", "resolution": "answer_remote"},
        ]
    }
    assert dreams._extract_question_resolution_rows(data) == [
        {"question": "Q2?", "resolution": "answer_remote"}
    ]


def test_attach_source_resolution_to_items():
    assert dreams._attach_source_resolution_to_items({"items": "nope"}, {}) == {
        "total_items": 0,
        "resolved_items": 0,
    }
    # No question rows -> nothing resolved.
    assert dreams._attach_source_resolution_to_items({"items": [{"origin_text": "x"}]}, {}) == {
        "total_items": 1,
        "resolved_items": 0,
    }


def test_attach_source_resolution_fuzzy_and_skips():
    idea = {
        "items": [
            "not-a-dict",
            {"origin_text": ""},  # empty origin skipped
            {"origin_text": "what is our long term product roadmap for 2027 and beyond"},
        ]
    }
    questions = {
        "questions": [
            {
                "question": "what is our long term product roadmap for 2027",
                "resolution": "answer_remote",
            }
        ]
    }
    stats = dreams._attach_source_resolution_to_items(idea, questions)
    assert stats["resolved_items"] == 1
    assert idea["items"][2]["source_resolution"] == "answer_remote"


def test_filter_idea_items_to_known_questions():
    assert dreams._filter_idea_items_to_known_questions({"items": "nope"}, {}) == {
        "before": 0,
        "after": 0,
        "dropped": 0,
    }
    # No question rows -> all dropped.
    idea = {"items": [{"origin_text": "x"}, {"origin_text": "y"}]}
    assert dreams._filter_idea_items_to_known_questions(idea, {}) == {
        "before": 2,
        "after": 0,
        "dropped": 2,
    }
    assert idea["items"] == []


def test_filter_idea_items_keeps_matches_and_skips():
    idea = {
        "items": [
            "not-a-dict",
            {"origin_text": ""},  # empty skipped
            {"origin_text": "How does scaling work in the system?"},
            {"origin_text": "unrelated question entirely"},
        ]
    }
    questions = {
        "questions": [
            {"question": "How does scaling work in the system?", "resolution": "answer_local"}
        ]
    }
    stats = dreams._filter_idea_items_to_known_questions(idea, questions)
    assert stats["after"] == 1
    assert idea["items"][0]["origin_text"] == "How does scaling work in the system?"


def test_remote_research_questions_invalid_list():
    assert dreams._remote_research_questions({"questions": "nope"}) == []


def test_index_items_by_origin_key_skips_non_dict():
    idx = dreams._index_items_by_origin_key(["not-a-dict", {"origin_text": "Hello"}])
    assert list(idx.keys()) == ["hello"]


def test_find_matching_item_empty_key():
    assert dreams._find_matching_item({}, "") == (None, "")


def test_annotate_matched_item_wraps_scalar_research():
    target = {"metadata": {"recommended_research": "single"}}
    seeded, rec_count = dreams._annotate_matched_item(target, {"topic": "t"}, "new topic")
    assert target["source_resolution"] == "answer_remote"
    assert seeded == 1
    assert target["metadata"]["recommended_research"] == ["single", "new topic"]
    assert rec_count == 2


def test_bridge_normalizes_non_list_items():
    ideas = {"items": "not-a-list"}
    bridged, stats = dreams._bridge_remote_questions_into_ideas(ideas, {"questions": []})
    assert bridged["items"] == []
    assert stats["remote_questions"] == 0


# --- _cleanup_question_artifacts ------------------------------------------


def test_cleanup_question_artifacts_logs_remove_failure(tmp_path, monkeypatch, caplog):
    project_id = "p1"
    base = tmp_path / project_id
    base.mkdir()
    (base / "open_questions_consolidated.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dreams, "get_settings", lambda: SimpleNamespace(memory_root=str(tmp_path)))
    monkeypatch.setattr(dreams.os, "remove", lambda p: (_ for _ in ()).throw(OSError("locked")))
    dreams._cleanup_question_artifacts(project_id)
    assert any("Failed removing questions artifact" in r.message for r in caplog.records)


# --- write_dream_output edge branches -------------------------------------


def _settings(tmp_path):
    return SimpleNamespace(memory_root=str(tmp_path))


def test_write_dream_output_non_str_and_whitespace_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    (tmp_path / "p1").mkdir()
    dream_data = {
        "items": [
            {"origin_text": 123},  # non-str -> returned as-is
            {"origin_text": "   "},  # all whitespace -> no rest, returned as-is
        ]
    }
    dreams.write_dream_output("p1", dream_data, "summary")
    written = json.loads((tmp_path / "p1" / "dream.json").read_text(encoding="utf-8"))
    assert written["items"][0]["origin_text"] == 123
    assert written["items"][1]["origin_text"] == "   "


def test_write_dream_output_items_not_list(tmp_path, monkeypatch):
    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    (tmp_path / "p1").mkdir()
    dreams.write_dream_output("p1", {"items": "not-a-list"}, "summary")
    written = json.loads((tmp_path / "p1" / "dream.json").read_text(encoding="utf-8"))
    assert written["items"] == []


def test_write_dream_output_existing_invalid_items_list(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    base = tmp_path / "p1"
    base.mkdir()
    (base / "dream.json").write_text(json.dumps({"items": "bad"}), encoding="utf-8")
    dreams.write_dream_output("p1", {"items": [{"origin_text": "new"}]}, "summary")
    assert any("invalid items" in r.message for r in caplog.records)


def test_write_dream_output_existing_invalid_top_level(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    base = tmp_path / "p1"
    base.mkdir()
    (base / "dream.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    dreams.write_dream_output("p1", {"items": [{"origin_text": "new"}]}, "summary")
    assert any("is invalid" in r.message for r in caplog.records)


def test_write_dream_output_outer_failure_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        dreams, "get_settings", lambda: (_ for _ in ()).throw(RuntimeError("settings boom"))
    )
    dreams.write_dream_output("p1", {"items": []}, "summary")
    assert any("Dream Writer failed" in r.message for r in caplog.records)


# --- _run_research_stage debug-write failure branches ---------------------


def test_run_research_stage_debug_write_failures(tmp_path, monkeypatch, caplog):
    project_id = "p1"
    base = tmp_path / project_id
    debug_dir = base / "debug"
    debug_dir.mkdir(parents=True)
    (debug_dir / "debug_dream_summary.txt").write_text("summary-debug", encoding="utf-8")

    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(dreams, "_safe_write_dreaming_debug", lambda *a, **k: None)
    monkeypatch.setattr(dreams, "run_research_agent", lambda *a, **k: {"items": [{"id": "x"}]})
    monkeypatch.setattr(dreams, "write_dream_output", lambda *a, **k: None)
    # write_debug_file always raises -> exercises both research-debug and
    # summary-mirror except branches (and the summary file read path).
    monkeypatch.setattr(
        dreams, "write_debug_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    )

    out = dreams._run_research_stage(project_id, "ts", {"items": []}, "summary")
    assert out == {"items": [{"id": "x"}]}
    messages = " ".join(r.message for r in caplog.records)
    assert "Failed writing dreaming research debug" in messages
    assert "Failed writing dreaming summary debug" in messages


def test_run_research_stage_summary_mirror_missing(tmp_path, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    project_id = "p1"
    (tmp_path / project_id).mkdir()
    monkeypatch.setattr(dreams, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(dreams, "_safe_write_dreaming_debug", lambda *a, **k: None)
    monkeypatch.setattr(dreams, "run_research_agent", lambda *a, **k: {"items": []})
    monkeypatch.setattr(dreams, "write_dream_output", lambda *a, **k: None)
    monkeypatch.setattr(dreams, "write_debug_file", lambda *a, **k: None)
    dreams._run_research_stage(project_id, "ts", {"items": []}, "summary")
    assert any("debug_dream_summary.txt missing" in r.message for r in caplog.records)


# --- dream() orchestrator failure branches --------------------------------


def test_dream_inner_stage_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        dreams, "get_settings", lambda: SimpleNamespace(memory_root="/x", enable_dream=True)
    )
    monkeypatch.setattr(
        dreams,
        "_run_questions_stage",
        lambda pid, ts: (_ for _ in ()).throw(RuntimeError("stage boom")),
    )
    dreams.dream("p1")  # must not raise
    assert any("stage boom" in r.message for r in caplog.records)


def test_dream_outer_failure_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        dreams, "get_settings", lambda: (_ for _ in ()).throw(RuntimeError("settings boom"))
    )
    dreams.dream("p1")  # must not raise
    assert any("Non-fatal dream cycle failure" in r.message for r in caplog.records)
