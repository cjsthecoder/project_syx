"""
Copyright (c) 2025-2026 Syx Project Contributors

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

from collections import deque

from app.core.db_models import Project
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
