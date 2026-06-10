"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.sleep.questions_consolidation.

Drives the deterministic open-question consolidation against a temp memory root:
the dedupe key helper, the no-source empty-artifact path, legacy-lock migration,
the full parse/dedup/sort/write happy path (including malformed-line skips and
ignore-drops), and the read/write failure fallbacks (faked via a selective
``open`` that raises only for the targeted paths).
"""
import builtins
import json
import os
from types import SimpleNamespace

import app.sleep.questions_consolidation as qc


def _settings(tmp_path):
    return SimpleNamespace(memory_root=str(tmp_path))


def _proj(tmp_path, project_id="p1"):
    d = os.path.join(str(tmp_path), project_id)
    os.makedirs(d, exist_ok=True)
    return d


# --- _normalize_question_key ----------------------------------------------


def test_normalize_question_key():
    # Quotes are stripped and non-alphanumeric runs collapse to single spaces,
    # so these equivalent phrasings produce the same key.
    a = qc._normalize_question_key("What's the Plan?", "Road-Map")
    b = qc._normalize_question_key("whats the plan", "road map")
    assert a == b == "whats the plan||road map"


# --- consolidate: no source file ------------------------------------------


def test_consolidate_no_source_writes_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    _proj(tmp_path)
    out = qc.consolidate_open_questions_artifact("p1")
    assert out == {"questions": []}
    written = json.loads(
        open(os.path.join(str(tmp_path), "p1", "open_questions_consolidated.json")).read()
    )
    assert written == {"questions": []}


def test_consolidate_no_source_write_failure_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    _proj(tmp_path)
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path).endswith("open_questions_consolidated.json"):
            raise OSError("write boom")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = qc.consolidate_open_questions_artifact("p1")
    assert out == {"questions": []}
    assert any("Failed writing empty consolidated" in r.message for r in caplog.records)


# --- legacy lock migration -------------------------------------------------


def test_consolidate_migrates_legacy_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    open(os.path.join(base, "open_questions.lock"), "w").close()
    qc.consolidate_open_questions_artifact("p1")
    # Legacy lock migrated under state/.
    assert os.path.isfile(os.path.join(base, "state", "open_questions.lock"))
    assert not os.path.isfile(os.path.join(base, "open_questions.lock"))


def test_consolidate_legacy_lock_migration_failure_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    open(os.path.join(base, "open_questions.lock"), "w").close()
    monkeypatch.setattr(qc.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    qc.consolidate_open_questions_artifact("p1")
    assert any("lock migration failed" in r.message for r in caplog.records)


# --- full happy path -------------------------------------------------------


def test_consolidate_parses_dedups_sorts_and_drops_ignore(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    lines = [
        "",  # blank -> skipped
        "{not json",  # invalid json -> skipped
        json.dumps([1, 2, 3]),  # non-dict -> skipped
        json.dumps({"topic": "t", "resolution": "answer_local"}),  # missing question -> skipped
        json.dumps(
            {
                "question": "Keep me?",
                "topic": "t",
                "resolution": "answer_remote",
                "ts": "2026-01-01",
            }
        ),
        json.dumps(
            {"question": "Keep me?", "topic": "t", "resolution": "answer_local", "ts": "2026-02-01"}
        ),  # newer dup -> wins
        json.dumps(
            {"question": "Drop me?", "topic": "t2", "resolution": "bogus", "ts": "2026-01-01"}
        ),  # unknown -> ignore -> dropped
        json.dumps(
            {
                "question": "Drop explicit?",
                "topic": "t3",
                "resolution": "ignore",
                "ts": "2026-01-01",
            }
        ),  # ignore -> dropped
    ]
    with open(os.path.join(base, "open_questions.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    out = qc.consolidate_open_questions_artifact("p1")
    questions = out["questions"]
    assert len(questions) == 1
    assert questions[0]["question"] == "Keep me?"
    # The newer duplicate (answer_local) won the collision.
    assert questions[0]["resolution"] == "answer_local"
    # Persisted to disk.
    written = json.loads(open(os.path.join(base, "open_questions_consolidated.json")).read())
    assert written == out


# --- read / write failure fallbacks ---------------------------------------


def test_consolidate_read_failure_writes_fallback(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    with open(os.path.join(base, "open_questions.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"question": "q", "resolution": "answer_local"}\n')
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path).endswith("open_questions.jsonl"):
            raise OSError("read boom")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = qc.consolidate_open_questions_artifact("p1")
    assert out == {"questions": []}
    assert any("Failed reading open_questions.jsonl" in r.message for r in caplog.records)


def test_consolidate_read_failure_and_fallback_write_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    with open(os.path.join(base, "open_questions.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"question": "q", "resolution": "answer_local"}\n')
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path).endswith(("open_questions.jsonl", "open_questions_consolidated.json")):
            raise OSError("io boom")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = qc.consolidate_open_questions_artifact("p1")
    assert out == {"questions": []}
    assert any("Failed writing fallback consolidated" in r.message for r in caplog.records)


def test_consolidate_final_write_failure_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(qc, "get_settings", lambda: _settings(tmp_path))
    base = _proj(tmp_path)
    with open(os.path.join(base, "open_questions.jsonl"), "w", encoding="utf-8") as f:
        f.write(
            '{"question": "q", "topic": "t", "resolution": "answer_local", "ts": "2026-01-01"}\n'
        )
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path).endswith("open_questions_consolidated.json"):
            raise OSError("write boom")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = qc.consolidate_open_questions_artifact("p1")
    # Returned in-memory even though the write failed.
    assert out["questions"][0]["question"] == "q"
    assert any("Failed writing consolidated artifact" in r.message for r in caplog.records)
