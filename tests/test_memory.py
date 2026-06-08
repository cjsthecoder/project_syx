"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for app.core.memory.MemoryManager.

Pure helpers are tested directly; persistence behavior (append, history,
pair-based roll-off) runs against an isolated temp SQLite engine with daily-RAG
disabled so no embedding/network calls occur.
"""

import json
from collections import deque

from sqlmodel import Session, select

from app.core import memory as memory_module
from app.core.db_models import ChatMessage, Project
from app.core.memory import MemoryManager


def _seed_project(engine, project_id, *, daily_rag_enabled=False):
    from sqlmodel import Session

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


def test_normalize_question_candidates_filters_and_defaults():
    raw = [
        {"question": "Why?", "topic": "t", "resolution": "answer_local"},
        {"question": "", "topic": "x", "resolution": "ignore"},  # empty -> dropped
        {"question": "Bad res", "resolution": "nonsense"},  # res -> ignore
        "not-a-dict",  # dropped
    ]
    out = MemoryManager._normalize_question_candidates(raw)
    assert out == [
        {"question": "Why?", "topic": "t", "resolution": "answer_local"},
        {"question": "Bad res", "topic": "", "resolution": "ignore"},
    ]


def test_normalize_question_candidates_non_list_returns_empty():
    assert MemoryManager._normalize_question_candidates("nope") == []


def test_pair_count_counts_adjacent_user_assistant():
    mm = MemoryManager()
    dq = deque(
        [
            {"role": "user"},
            {"role": "assistant"},
            {"role": "user"},
            {"role": "assistant"},
            {"role": "user"},  # trailing unpaired
        ]
    )
    assert mm._pair_count(dq) == 2


def test_last_context_tokens_clamps_negative():
    mm = MemoryManager()
    mm.set_last_context_tokens("p", -10)
    assert mm.get_last_context_tokens("p") == 0
    mm.set_last_context_tokens("p", 42)
    assert mm.get_last_context_tokens("p") == 42


def test_get_last_context_tokens_default_zero():
    mm = MemoryManager()
    assert mm.get_last_context_tokens("never-seen") == 0


def test_append_and_read_history_round_trip(fresh_memory_manager, settings_override):
    settings_override(chat_history_limit_pairs=5, chat_history_limit=20)
    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("p1", "hello")
    mm.append_assistant_message("p1", "hi there")  # tagging skipped (no user_text_for_tagging)

    history = mm.get_project_history("p1")
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert [m["content"] for m in history] == ["hello", "hi there"]
    assert mm.get_active_pair_count("p1") == 1


def test_rolloff_drops_oldest_pair_when_over_limit(db, fresh_memory_manager, settings_override):
    settings_override(chat_history_limit_pairs=1, chat_history_limit=10)
    _seed_project(db, "p2", daily_rag_enabled=False)
    mm = fresh_memory_manager.get_memory_manager()

    mm.append_user_message("p2", "q1")
    mm.append_assistant_message("p2", "a1")
    mm.append_user_message("p2", "q2")
    mm.append_assistant_message("p2", "a2")

    # pair_limit is 1, so only the most recent pair should remain.
    history = mm.get_project_history("p2")
    assert mm.get_active_pair_count("p2") == 1
    assert [m["content"] for m in history] == ["q2", "a2"]


def test_get_memory_stats_shape(fresh_memory_manager):
    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("p3", "x")
    stats = mm.get_memory_stats()
    assert stats["memory_mode"] == "persistent"
    assert stats["total_conversations"] >= 1
    assert set(stats["features_available"].keys()) == {
        "rag_search",
        "memory_pruning",
        "conversation_storage",
    }


# ---------------------------------------------------------------------------
# Tagging path of append_assistant_message and the daily-append/forget branches
# of roll-off. These mock the tagger, pruner, and daily store so the branches
# are exercised deterministically and offline; they pin behavior ahead of
# breaking these large methods into helpers.
# ---------------------------------------------------------------------------

def _tagger_returning(meta):
    def _fake_tag_pair(user_text, assistant_text, *, previous_pair_text=None, project_id=None):
        return dict(meta)
    return _fake_tag_pair


def test_append_assistant_message_tagging_persists_metadata(
    db, fresh_memory_manager, settings_override, monkeypatch
):
    settings_override(chat_history_limit_pairs=5, chat_history_limit=20)
    _seed_project(db, "pT", daily_rag_enabled=False)

    monkeypatch.setattr(
        memory_module,
        "tag_pair",
        _tagger_returning(
            {"topics": "alpha", "intent": "learn", "type": "fact", "semantic_handle": "h1", "questions": []}
        ),
    )
    # Force a non-identity prune so the pruned-text path is exercised and stored.
    monkeypatch.setattr(memory_module, "_prune_assistant_for_tagger", lambda **kw: "PRUNED a1")

    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("pT", "q1")
    mm.append_assistant_message("pT", "a1", user_text_for_tagging="q1")

    with Session(db) as s:
        row = s.exec(
            select(ChatMessage).where(ChatMessage.project_id == "pT", ChatMessage.role == "assistant")
        ).first()
        assert row.semantic_handle == "h1"
        meta = json.loads(row.tags_meta_json)
        assert meta["topics"] == "alpha"
        assert meta["intent"] == "learn"
        assert meta["_pruned_assistant_text"] == "PRUNED a1"
        # Semantic handle is mirrored onto the project for cross-flush persistence.
        proj = s.get(Project, "pT")
        assert proj.last_semantic_handle == "h1"


def test_rolloff_appends_pair_to_daily_when_enabled(
    db, fresh_memory_manager, settings_override, monkeypatch
):
    settings_override(chat_history_limit_pairs=1, chat_history_limit=10)
    _seed_project(db, "pD", daily_rag_enabled=True)

    monkeypatch.setattr(
        memory_module,
        "tag_pair",
        _tagger_returning(
            {"topics": "alpha", "intent": "learn", "type": "fact", "semantic_handle": "h", "questions": []}
        ),
    )
    monkeypatch.setattr(memory_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"])

    calls = []
    monkeypatch.setattr(
        memory_module,
        "append_pair",
        lambda *a, **k: (calls.append((a, k)) or True),
    )

    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("pD", "q1")
    mm.append_assistant_message("pD", "a1", user_text_for_tagging="q1")
    mm.append_user_message("pD", "q2")
    mm.append_assistant_message("pD", "a2", user_text_for_tagging="q2")

    # Exactly the first (oldest) pair rolled off and was appended to daily.
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "pD"
    assert args[1] == "User: q1\nAssistant: a1"
    assert kwargs["namespace"] == "other"
    assert kwargs["keep"] is False
    assert kwargs["embed_override"].startswith("#topics: alpha")
    # Private rolloff-only fields must be stripped from the persisted tags_meta.
    assert all(not str(key).startswith("_") for key in kwargs["tags_meta"])


def test_rolloff_skips_daily_append_when_forget(
    db, fresh_memory_manager, settings_override, monkeypatch
):
    settings_override(chat_history_limit_pairs=1, chat_history_limit=10)
    _seed_project(db, "pF", daily_rag_enabled=True)

    monkeypatch.setattr(memory_module, "_prune_assistant_for_tagger", lambda **kw: kw["assistant_text"])
    calls = []
    monkeypatch.setattr(
        memory_module,
        "append_pair",
        lambda *a, **k: (calls.append((a, k)) or True),
    )

    mm = fresh_memory_manager.get_memory_manager()
    mm.append_user_message("pF", "q1")
    mm.append_assistant_message("pF", "a1", forget=True)
    mm.append_user_message("pF", "q2")
    mm.append_assistant_message("pF", "a2", forget=True)

    # Forgotten pair is evicted but never appended to daily memory.
    assert calls == []
    assert mm.get_active_pair_count("pF") == 1
