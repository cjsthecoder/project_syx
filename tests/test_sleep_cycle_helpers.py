"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for helpers extracted from ``_sleep_cycle_worker``.

Covers the pure formatting/selection helpers (public-tag filtering, the daily
tags block, and summary boundary stripping) plus the per-project flush loop
``_flush_project_pairs`` driven with a fake DB session and patched dependencies
so no real database, tagger, embeddings, or FAISS are touched.
"""
from types import SimpleNamespace

import app.sleep.cycle as cycle
from app.sleep.cycle import (
    _build_pair_tags_block,
    _flush_project_pairs,
    _public_tags_meta,
    _SleepCycleStats,
    _summary_content_only,
)

# --- _public_tags_meta --------------------------------------------------------


def test_public_tags_meta_strips_underscore_keys():
    meta = {"topics": "a", "_pruned_assistant_text": "x", "_internal": 1, "intent": "b"}
    out = _public_tags_meta(meta)
    assert out == {"topics": "a", "intent": "b"}


def test_public_tags_meta_none_for_non_dict():
    assert _public_tags_meta(None) is None
    assert _public_tags_meta("nope") is None


# --- _build_pair_tags_block ---------------------------------------------------


def test_build_pair_tags_block_with_semantic_handle():
    block = _build_pair_tags_block(
        {"topics": "t1", "intent": "ask", "type": "note", "semantic_handle": "h"}
    )
    assert block == "#topics: t1\n#intent: ask\n#type: note\n#semantic_handle: h\n"


def test_build_pair_tags_block_without_semantic_handle():
    block = _build_pair_tags_block({"topics": "t1", "intent": "ask", "type": "note"})
    assert block == "#topics: t1\n#intent: ask\n#type: note\n"


def test_build_pair_tags_block_empty_for_non_dict():
    assert _build_pair_tags_block(None) == ""


# --- _summary_content_only ----------------------------------------------------


def test_summary_content_only_strips_boundary_lines():
    text = "=== begin ===\nhello\nworld\n=== end ==="
    assert _summary_content_only(text) == "hello\nworld"


def test_summary_content_only_empty_when_only_boundaries():
    text = "=== begin ===\n=== end ==="
    assert _summary_content_only(text) == ""


def test_summary_content_only_handles_none():
    assert _summary_content_only(None) == ""


# --- _flush_project_pairs -----------------------------------------------------


class _FakeExec:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Minimal session double supporting the queries used by the flush loop."""

    def __init__(self, msgs, rows_by_id):
        self._msgs = msgs
        self._rows_by_id = rows_by_id
        self.deleted = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def exec(self, _query):
        return _FakeExec(self._msgs)

    def get(self, _model, row_id):
        return self._rows_by_id.get(row_id)

    def delete(self, row):
        self.deleted.append(getattr(row, "id", None))

    def commit(self):
        self.commits += 1


def _msg(role, content, mid, *, forget=False, keep=False, namespace="other", tags_json=None):
    return SimpleNamespace(
        role=role,
        content=content,
        id=mid,
        created_at=None,
        forget=forget,
        keep=keep,
        namespace=namespace,
        tags_meta_json=tags_json,
    )


def _patch_flush_env(monkeypatch, msgs, *, append_ok=True):
    rows_by_id = {m.id: m for m in msgs}
    session = _FakeSession(msgs, rows_by_id)
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    monkeypatch.setattr(cycle, "count_tokens", lambda *_a, **_k: 5)
    monkeypatch.setattr(
        cycle,
        "_prune_assistant_for_tagger",
        lambda *, project_id, assistant_text, settings: assistant_text,
    )
    monkeypatch.setattr(
        cycle, "tag_pair_tagger", lambda *a, **k: {"topics": "t", "intent": "i", "type": "n"}
    )
    appended = []

    def _fake_append_pair(pid, pair_text, *a, **k):
        appended.append((pid, pair_text))
        return append_ok

    monkeypatch.setattr(cycle, "append_pair", _fake_append_pair)
    return session, appended


def test_flush_project_pairs_appends_and_deletes(monkeypatch):
    msgs = [_msg("user", "hi", 1), _msg("assistant", "hello", 2)]
    session, appended = _patch_flush_env(monkeypatch, msgs)
    stats = _SleepCycleStats()

    flushed = _flush_project_pairs("p1", pair_limit=10, stats=stats)

    assert flushed == 1
    assert stats.items_in == 1
    assert stats.items_out == 1
    assert len(appended) == 1
    assert sorted(session.deleted) == [1, 2]


def test_flush_project_pairs_forget_deletes_without_append(monkeypatch):
    msgs = [_msg("user", "hi", 1), _msg("assistant", "secret", 2, forget=True)]
    session, appended = _patch_flush_env(monkeypatch, msgs)
    stats = _SleepCycleStats()

    flushed = _flush_project_pairs("p1", pair_limit=10, stats=stats)

    assert flushed == 0
    assert stats.items_in == 1
    assert stats.items_out == 0
    assert appended == []
    assert sorted(session.deleted) == [1, 2]


def test_flush_project_pairs_keeps_rows_when_append_fails(monkeypatch):
    msgs = [_msg("user", "hi", 1), _msg("assistant", "hello", 2)]
    session, appended = _patch_flush_env(monkeypatch, msgs, append_ok=False)
    stats = _SleepCycleStats()

    flushed = _flush_project_pairs("p1", pair_limit=10, stats=stats)

    assert flushed == 0
    assert stats.items_in == 1
    assert stats.items_out == 0
    assert len(appended) == 1
    # Append failed -> rows are not deleted.
    assert session.deleted == []
