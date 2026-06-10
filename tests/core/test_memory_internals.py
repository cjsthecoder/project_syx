"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Internal-branch coverage for app.core.memory.

Complements test_memory.py by exercising the pruning/debug helpers, the
open-questions artifact writer, deque hydration/cleanup, roll-off metadata
reuse, and the module-level convenience wrappers. Boundaries (DB session,
tagger, pruner, daily store, debug writer) are faked so nothing reaches
embeddings or the network.
"""

import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core import memory as memory_module
from app.core.db_models import ChatMessage, Project
from app.core.memory import MemoryManager
from sqlmodel import Session


def _seed_project(engine, project_id, *, daily_rag_enabled=False):
    with Session(engine) as session:
        session.add(
            Project(
                id=project_id,
                name=project_id,
                description=project_id,
                system=False,
                daily_rag_enabled=daily_rag_enabled,
            )
        )
        session.commit()


def _raise(*_a, **_k):
    raise RuntimeError("boom")


# --- _resolve_response_pruning_rules_path ---------------------------------


def test_resolve_rules_path_absolute_returned_as_is():
    from pathlib import Path

    from app.core.memory import _resolve_response_pruning_rules_path

    p = _resolve_response_pruning_rules_path(str(Path("/abs/rules.json")))
    assert p == Path("/abs/rules.json")


def test_resolve_rules_path_prefers_cwd(tmp_path, monkeypatch):
    from app.core.memory import _resolve_response_pruning_rules_path

    monkeypatch.chdir(tmp_path)
    (tmp_path / "rules.json").write_text("{}", encoding="utf-8")
    resolved = _resolve_response_pruning_rules_path("rules.json")
    assert resolved == tmp_path / "rules.json"


def test_resolve_rules_path_falls_back_to_repo_root(tmp_path, monkeypatch):
    from app.core.memory import _REPO_ROOT, _resolve_response_pruning_rules_path

    monkeypatch.chdir(tmp_path)
    resolved = _resolve_response_pruning_rules_path("does/not/exist.json")
    assert resolved == _REPO_ROOT / "does/not/exist.json"


# --- _get_response_pruner (build + cache) ---------------------------------


def test_get_response_pruner_builds_then_caches(monkeypatch):
    from app.core import memory
    from app.core.config import get_settings

    monkeypatch.setattr(memory, "_PRUNER_CACHE", None)
    monkeypatch.setattr(memory, "_PRUNER_CACHE_KEY", None)
    settings = get_settings()
    first = memory._get_response_pruner(settings)
    second = memory._get_response_pruner(settings)  # identical config -> cache hit
    assert first is second


# --- _write_light_pruner_debug --------------------------------------------


def test_write_light_pruner_debug_with_result(monkeypatch):
    writes = []
    monkeypatch.setattr(
        memory_module, "write_debug_file", lambda pid, path, body: writes.append(body)
    )
    result = SimpleNamespace(
        changed=True,
        trimmed_side="front",
        front_units_removed=1,
        end_span_removed=0,
        blocked_by_safety=False,
    )
    memory_module._write_light_pruner_debug(
        project_id="p1", original_response="long original", pruned_response="short", result=result
    )
    assert writes and "trimmed_side: front" in writes[0]


def test_write_light_pruner_debug_with_error(monkeypatch):
    writes = []
    monkeypatch.setattr(
        memory_module, "write_debug_file", lambda pid, path, body: writes.append(body)
    )
    memory_module._write_light_pruner_debug(
        project_id="p1",
        original_response="o",
        pruned_response="o",
        result=None,
        error=ValueError("kaboom"),
    )
    assert writes and "error: kaboom" in writes[0]


def test_write_light_pruner_debug_swallows_failure(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "count_tokens", _raise)
    memory_module._write_light_pruner_debug(
        project_id="p1", original_response="o", pruned_response="o", result=None
    )
    assert any("Failed writing debug dump" in r.message for r in caplog.records)


# --- _prune_assistant_for_tagger ------------------------------------------


def test_prune_disabled_returns_original(monkeypatch):
    monkeypatch.setattr(memory_module, "write_debug_file", lambda *a, **k: None)
    settings = SimpleNamespace(response_pruning_enabled=False)
    out = memory_module._prune_assistant_for_tagger(
        project_id="p1", assistant_text="hello world", settings=settings
    )
    assert out == "hello world"


def test_prune_enabled_returns_pruned_text(monkeypatch):
    monkeypatch.setattr(memory_module, "write_debug_file", lambda *a, **k: None)
    from app.core.config import get_settings

    out = memory_module._prune_assistant_for_tagger(
        project_id="p1", assistant_text="hello world", settings=get_settings()
    )
    assert isinstance(out, str)


def test_prune_failure_returns_original(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "write_debug_file", lambda *a, **k: None)
    monkeypatch.setattr(memory_module, "_get_response_pruner", _raise)
    settings = SimpleNamespace(response_pruning_enabled=True)
    out = memory_module._prune_assistant_for_tagger(
        project_id="p1", assistant_text="original text", settings=settings
    )
    assert out == "original text"
    assert any("Failed pruning assistant response" in r.message for r in caplog.records)


# --- _append_open_questions_artifact --------------------------------------


def _questions():
    return [{"question": "Why?", "topic": "t", "resolution": "ignore"}]


def test_append_open_questions_noop_when_empty(temp_memory_root):
    mm = MemoryManager()
    mm._append_open_questions_artifact(
        project_id="p1",
        assistant_message_id=2,
        user_message_id=1,
        namespace="other",
        semantic_handle="h",
        questions=[],
    )
    assert not os.path.exists(os.path.join(str(temp_memory_root), "p1", "open_questions.jsonl"))


def test_append_open_questions_writes_lines(temp_memory_root):
    mm = MemoryManager()
    mm._append_open_questions_artifact(
        project_id="p1",
        assistant_message_id=2,
        user_message_id=1,
        namespace="other",
        semantic_handle="h",
        questions=_questions(),
    )
    artifact = os.path.join(str(temp_memory_root), "p1", "open_questions.jsonl")
    lines = open(artifact, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["pair_id"] == "1:2" and payload["question"] == "Why?"


def test_append_open_questions_migrates_legacy_lock(temp_memory_root):
    base = os.path.join(str(temp_memory_root), "p1")
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "open_questions.lock"), "w").close()  # legacy lock present
    mm = MemoryManager()
    mm._append_open_questions_artifact(
        project_id="p1",
        assistant_message_id=2,
        user_message_id=1,
        namespace="other",
        semantic_handle="h",
        questions=_questions(),
    )
    # The legacy lock was migrated out of the project root (and the FileLock that
    # used it under state/ was released and cleaned up afterwards).
    assert not os.path.isfile(os.path.join(base, "open_questions.lock"))
    assert os.path.isfile(os.path.join(base, "open_questions.jsonl"))


def test_append_open_questions_logs_migration_failure(temp_memory_root, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    base = os.path.join(str(temp_memory_root), "p1")
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "open_questions.lock"), "w").close()
    # os.replace is guarded against OSError specifically.
    monkeypatch.setattr(
        memory_module.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("denied"))
    )
    mm = MemoryManager()
    mm._append_open_questions_artifact(
        project_id="p1",
        assistant_message_id=2,
        user_message_id=1,
        namespace="other",
        semantic_handle="h",
        questions=_questions(),
    )
    assert any("lock migration failed" in r.message for r in caplog.records)


def test_append_open_questions_logs_outer_failure(temp_memory_root, monkeypatch, caplog):
    monkeypatch.setattr(memory_module.os, "makedirs", _raise)
    mm = MemoryManager()
    mm._append_open_questions_artifact(
        project_id="p1",
        assistant_message_id=2,
        user_message_id=1,
        namespace="other",
        semantic_handle="h",
        questions=_questions(),
    )
    assert any("Failed writing open_questions.jsonl" in r.message for r in caplog.records)


# --- _ensure_loaded (DB hydration) ----------------------------------------


def test_ensure_loaded_hydrates_from_db(db, fresh_memory_manager):
    now = datetime.now(timezone.utc)
    with Session(db) as session:
        session.add(ChatMessage(project_id="pL", role="user", content="q", created_at=now))
        session.add(
            ChatMessage(
                project_id="pL",
                role="assistant",
                content="a",
                created_at=now + timedelta(seconds=1),
            )
        )
        session.commit()
    mm = fresh_memory_manager.get_memory_manager()
    history = mm.get_project_history("pL")
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_ensure_loaded_logs_on_db_failure(fresh_memory_manager, monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "get_session", _raise)
    mm = fresh_memory_manager.get_memory_manager()
    mm._ensure_loaded("pErr")
    assert any("Failed to load history" in r.message for r in caplog.records)
    assert list(mm.project_deques["pErr"]) == []


# --- append_*_message no-project guards -----------------------------------


def test_append_user_message_noop_without_project(fresh_memory_manager):
    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("", "x")  # must not raise or load anything
    assert "" not in mm.project_deques


def test_append_assistant_message_noop_without_project(fresh_memory_manager):
    mm = fresh_memory_manager.get_memory_manager()
    mm.append_assistant_message("", "x")
    assert "" not in mm.project_deques


# --- _find_source_user_message_id -----------------------------------------


def test_find_source_user_message_id_handles_exception(caplog):
    class _RaisingDQ:
        def __bool__(self):
            return True

        def __getitem__(self, _i):
            raise RuntimeError("index boom")

    mm = MemoryManager()
    mm.project_deques["x"] = _RaisingDQ()
    assert mm._find_source_user_message_id("x") is None
    assert any("source user lookup failed" in r.message for r in caplog.records)


# --- _tag_assistant_pair failure branches ---------------------------------


def test_tag_assistant_pair_serialization_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        memory_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"]
    )
    # A set is not JSON-serializable -> tags_meta_json serialization fails.
    monkeypatch.setattr(
        memory_module,
        "tag_pair",
        lambda *a, **k: {"topics": "t", "semantic_handle": {1, 2}, "questions": []},
    )
    mm = MemoryManager()
    result = mm._tag_assistant_pair(
        project_id="p1",
        content="a",
        user_text_for_tagging="q",
        previous_pair_text_for_tagging=None,
        skip_tagger=False,
    )
    assert result.tags_meta_json is None
    assert any("tag metadata serialization failed" in r.message for r in caplog.records)


def test_tag_assistant_pair_tagger_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        memory_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"]
    )
    monkeypatch.setattr(memory_module, "tag_pair", _raise)
    mm = MemoryManager()
    result = mm._tag_assistant_pair(
        project_id="p1",
        content="a",
        user_text_for_tagging="q",
        previous_pair_text_for_tagging=None,
        skip_tagger=False,
    )
    assert result.tags_meta is None and result.semantic_handle is None
    assert any("tagging failed" in r.message for r in caplog.records)


# --- _persist_assistant_row semantic-handle mirror failure ----------------


def test_persist_assistant_row_logs_handle_update_failure(monkeypatch, caplog):
    class _FakeSession:
        def add(self, _obj):
            pass

        def get(self, _model, _pk):
            raise RuntimeError("get failed")

        def commit(self):
            pass

        def refresh(self, obj):
            obj.id = 99

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(memory_module, "get_session", lambda: _FakeSession())
    mm = MemoryManager()
    msg_id = mm._persist_assistant_row(
        project_id="p1",
        content="a",
        now=datetime.now(timezone.utc),
        forget=False,
        ns="other",
        tags_meta_json=None,
        semantic_handle="handle",
    )
    assert msg_id == 99
    assert any("failed updating project semantic handle" in r.message for r in caplog.records)


# --- _pair_count odd-start branch -----------------------------------------


def test_pair_count_skips_leading_assistant():
    mm = MemoryManager()
    dq = deque([{"role": "assistant"}, {"role": "user"}, {"role": "assistant"}])
    assert mm._pair_count(dq) == 1  # the leading assistant is skipped


# --- _rolloff_oldest_pair stray handling ----------------------------------


def test_rolloff_clears_stray_then_returns_when_under_two(db):
    now = datetime.now(timezone.utc)
    with Session(db) as session:
        session.add(
            ChatMessage(id=501, project_id="pS", role="assistant", content="a", created_at=now)
        )
        session.commit()
    mm = MemoryManager()
    dq = deque([{"role": "assistant", "id": 501}, {"role": "assistant", "id": 502}])
    mm._rolloff_oldest_pair("pS", dq)
    assert len(dq) == 1  # stray head dropped, then bailed out (fewer than 2 remain)
    with Session(db) as session:
        assert session.get(ChatMessage, 501) is None  # stray row deleted


def test_rolloff_stray_delete_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "get_session", _raise)
    mm = MemoryManager()
    dq = deque([{"role": "assistant", "id": 1}, {"role": "assistant", "id": 2}])
    mm._rolloff_oldest_pair("pS", dq)
    assert any("Failed deleting stray message" in r.message for r in caplog.records)


# --- _append_pair_to_daily metadata reuse + failures ----------------------


def test_append_pair_to_daily_invalid_tags_json(monkeypatch):
    appended = []
    monkeypatch.setattr(memory_module, "append_pair", lambda *a, **k: appended.append((a, k)))
    mm = MemoryManager()
    mm._is_daily_enabled = lambda _pid: True
    mm._append_pair_to_daily(
        "p1",
        {"content": "q", "id": 1},
        {"content": "a", "id": 2, "tags_meta_json": "{not valid json"},
    )
    assert appended  # pair still appended; bad metadata simply ignored


def test_append_pair_to_daily_uses_pruned_text_from_meta(monkeypatch):
    appended = []
    monkeypatch.setattr(memory_module, "append_pair", lambda *a, **k: appended.append((a, k)))
    mm = MemoryManager()
    mm._is_daily_enabled = lambda _pid: True
    meta = json.dumps({"_pruned_assistant_text": "PRUNED", "topics": "t"})
    mm._append_pair_to_daily(
        "p1",
        {"content": "q", "id": 1},
        {"content": "RAW", "id": 2, "tags_meta_json": meta},
    )
    args, _kwargs = appended[0]
    assert "PRUNED" in args[1]  # pair_text uses the pruned assistant text


def test_append_pair_to_daily_logs_on_append_failure(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "append_pair", _raise)
    mm = MemoryManager()
    mm._is_daily_enabled = lambda _pid: True
    mm._append_pair_to_daily("p1", {"content": "q", "id": 1}, {"content": "a", "id": 2})
    assert any("rolloff append failed" in r.message for r in caplog.records)


# --- _delete_pair_rows failure --------------------------------------------


def test_delete_pair_rows_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "get_session", _raise)
    mm = MemoryManager()
    mm._delete_pair_rows({"id": 1}, {"id": 2})
    assert any("Failed deleting rolled-off DB rows" in r.message for r in caplog.records)


# --- _cleanup_unpaired_edges ----------------------------------------------


def test_cleanup_unpaired_edges_trims_head_and_tail(db):
    now = datetime.now(timezone.utc)
    with Session(db) as session:
        session.add(
            ChatMessage(id=601, project_id="pC", role="assistant", content="orphan", created_at=now)
        )
        session.add(ChatMessage(id=602, project_id="pC", role="user", content="u", created_at=now))
        session.add(
            ChatMessage(id=603, project_id="pC", role="assistant", content="a", created_at=now)
        )
        session.add(
            ChatMessage(id=604, project_id="pC", role="user", content="trailing", created_at=now)
        )
        session.commit()
    mm = MemoryManager()
    dq = deque(
        [
            {"role": "assistant", "id": 601},
            {"role": "user", "id": 602},
            {"role": "assistant", "id": 603},
            {"role": "user", "id": 604},
        ]
    )
    mm._cleanup_unpaired_edges("pC", dq)
    assert [m["id"] for m in dq] == [602, 603]
    with Session(db) as session:
        assert session.get(ChatMessage, 601) is None  # orphan head deleted
        assert session.get(ChatMessage, 604) is None  # trailing user deleted


def test_cleanup_unpaired_edges_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "get_session", _raise)
    mm = MemoryManager()
    dq = deque([{"role": "assistant", "id": 1}, {"role": "user", "id": 2}])
    mm._cleanup_unpaired_edges("pC", dq)
    # Both edges still trimmed despite the delete failures being logged.
    assert len(dq) == 0
    assert any("Failed deleting orphan assistant" in r.message for r in caplog.records)
    assert any("Failed deleting trailing unpaired" in r.message for r in caplog.records)


# --- _is_daily_enabled -----------------------------------------------------


def test_is_daily_enabled_missing_project_defaults_true(db):
    mm = MemoryManager()
    assert mm._is_daily_enabled("never-seen") is True


def test_is_daily_enabled_reads_flag(db):
    _seed_project(db, "pE", daily_rag_enabled=False)
    mm = MemoryManager()
    assert mm._is_daily_enabled("pE") is False


def test_is_daily_enabled_defaults_true_on_error(monkeypatch, caplog):
    monkeypatch.setattr(memory_module, "get_session", _raise)
    mm = MemoryManager()
    assert mm._is_daily_enabled("pX") is True
    assert any("Failed to read project daily flag" in r.message for r in caplog.records)


# --- deprecated / stub methods --------------------------------------------


def test_get_conversation_history_returns_empty():
    assert MemoryManager().get_conversation_history("c1", limit=5) == []


def test_search_memory_returns_stub():
    out = MemoryManager().search_memory("hello")
    assert out and out[0]["source"] == "stub"


def test_cleanup_old_memories_returns_stub():
    out = MemoryManager().cleanup_old_memories(retention_days=7)
    assert out["status"] == "stub_mode" and out["retention_days"] == 7


# --- module-level convenience wrappers ------------------------------------


def test_module_context_token_wrappers(fresh_memory_manager):
    memory_module.set_last_context_tokens("pW", 33)
    assert memory_module.get_last_context_tokens("pW") == 33


def test_search_conversation_memory_wrapper(fresh_memory_manager):
    out = memory_module.search_conversation_memory("q")
    assert out and out[0]["source"] == "stub"
