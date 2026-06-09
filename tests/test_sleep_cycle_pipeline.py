"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for the sleep-cycle orchestration helpers in app.sleep.cycle.

Every external boundary is faked (DB session, memory manager, tagger, pruner,
daily store, dream/auto-accept, FAISS rebuild/load, debug writers) and the
filesystem uses a temp memory root, so these drive the flush/backfill/dream/
merge/cleanup/pipeline branches without touching a model, FAISS, or the network.
"""
from types import SimpleNamespace

import app.sleep.cycle as cycle

# --- _delete_pair_rows -----------------------------------------------------


class _DelSession:
    def __init__(self, rows, *, raise_on=None):
        self._rows = rows
        self._raise_on = raise_on
        self.deleted = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, _model, row_id):
        if self._raise_on == "get":
            raise RuntimeError("db get boom")
        return self._rows.get(row_id)

    def delete(self, row):
        self.deleted.append(getattr(row, "id", None))

    def commit(self):
        self.committed = True


def test_delete_pair_rows_happy(monkeypatch):
    rows = {1: SimpleNamespace(id=1), 2: SimpleNamespace(id=2)}
    session = _DelSession(rows)
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    assert cycle._delete_pair_rows("p1", 1, 2) is True
    assert sorted(session.deleted) == [1, 2] and session.committed


def test_delete_pair_rows_missing_rows(monkeypatch):
    session = _DelSession({})  # get returns None for both
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    assert cycle._delete_pair_rows("p1", 1, 2) is True
    assert session.deleted == []


def test_delete_pair_rows_failure_logged(monkeypatch, caplog):
    session = _DelSession({}, raise_on="get")
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    assert cycle._delete_pair_rows("p1", 1, 2) is False
    assert any("DB delete failed" in r.message for r in caplog.records)


# --- _prepare_pair_for_daily ----------------------------------------------


def _row(**kw):
    base = dict(
        content="", created_at=None, namespace="other", keep=False, tags_meta_json=None, id=1
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_prepare(monkeypatch, *, pruned=None, tag_result=None):
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        cycle,
        "_prune_assistant_for_tagger",
        lambda *, project_id, assistant_text, settings: (
            pruned if pruned is not None else assistant_text
        ),
    )
    monkeypatch.setattr(
        cycle,
        "tag_pair_tagger",
        lambda *a, **k: (
            tag_result if tag_result is not None else {"topics": "t", "intent": "i", "type": "n"}
        ),
    )


def test_prepare_pair_uses_stored_tags_json(monkeypatch):
    _patch_prepare(monkeypatch)
    import json

    u = _row(content="hi", id=1)
    a = _row(
        content="hello",
        id=2,
        tags_meta_json=json.dumps({"topics": "x", "_pruned_assistant_text": "pruned"}),
    )
    pair_text, embed_text, public, ns, keep, created = cycle._prepare_pair_for_daily(
        u, a, "p1", None
    )
    # Stored pruned text is reused (not re-pruned), and private keys stripped from public.
    assert "pruned" in pair_text
    assert "_pruned_assistant_text" not in public and public["topics"] == "x"


def test_prepare_pair_bad_tags_json_falls_back_to_tagger(monkeypatch, caplog):
    _patch_prepare(monkeypatch)
    u = _row(content="hi", id=1)
    a = _row(content="hello", id=2, tags_meta_json="{not valid json")
    pair_text, embed_text, public, ns, keep, created = cycle._prepare_pair_for_daily(
        u, a, "p1", None
    )
    assert public == {"topics": "t", "intent": "i", "type": "n"}
    assert any("Failed parsing tags_meta_json" in r.message for r in caplog.records)


def test_prepare_pair_prune_changes_text_updates_meta(monkeypatch):
    # Stored tags dict + a pruner that shortens the assistant text -> meta is
    # updated with the pruned text and re-used downstream.
    _patch_prepare(monkeypatch, pruned="short")
    import json

    u = _row(
        content="hi", id=1, created_at=SimpleNamespace(strftime=lambda fmt: "2026-01-01T00:00:00Z")
    )
    a = _row(
        content="a very long assistant answer", id=2, tags_meta_json=json.dumps({"topics": "x"})
    )
    pair_text, embed_text, public, ns, keep, created = cycle._prepare_pair_for_daily(
        u, a, "p1", None
    )
    assert "short" in pair_text and created == "2026-01-01T00:00:00Z"


def test_prepare_pair_no_tags_json_tags_and_prunes(monkeypatch):
    # No stored tags -> tagger runs; pruner shortens -> tag result merged with pruned text.
    _patch_prepare(monkeypatch, pruned="short")
    u = _row(content="hi", id=1)
    a = _row(content="long answer", id=2, namespace="CODE", keep=True)
    pair_text, embed_text, public, ns, keep, created = cycle._prepare_pair_for_daily(
        u, a, "p1", None
    )
    assert ns == "code" and keep is True and "short" in pair_text


# --- _flush_project_pairs orphan branch -----------------------------------


class _FlushSession:
    def __init__(self, msgs, rows_by_id, *, raise_on_orphan=False):
        self._msgs = msgs
        self._rows_by_id = rows_by_id
        self._raise_on_orphan = raise_on_orphan
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def exec(self, _q):
        return SimpleNamespace(all=lambda: list(self._msgs))

    def get(self, _model, row_id):
        if self._raise_on_orphan:
            raise RuntimeError("orphan get boom")
        return self._rows_by_id.get(row_id)

    def delete(self, row):
        self.deleted.append(getattr(row, "id", None))

    def commit(self):
        pass


def test_flush_project_pairs_deletes_orphan_row(monkeypatch):
    # Leading assistant row (no preceding user) is an orphan -> single-row delete.
    msgs = [_row(role="assistant", content="x", id=9)]
    msgs[0].role = "assistant"
    session = _FlushSession(msgs, {9: msgs[0]})
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    stats = cycle._SleepCycleStats()
    # Two messages needed for the loop (i+1 < n); add a trailing user row.
    trailing = _row(role="user", content="late", id=10)
    trailing.role = "user"
    session._msgs = [msgs[0], trailing]
    flushed = cycle._flush_project_pairs("p1", pair_limit=10, stats=stats)
    assert flushed == 0
    assert 9 in session.deleted


def test_flush_project_pairs_orphan_delete_failure_logged(monkeypatch, caplog):
    a = _row(role="assistant", content="x", id=9)
    a.role = "assistant"
    b = _row(role="user", content="late", id=10)
    b.role = "user"
    session = _FlushSession([a, b], {9: a}, raise_on_orphan=True)
    monkeypatch.setattr(cycle, "get_session", lambda: session)
    stats = cycle._SleepCycleStats()
    cycle._flush_project_pairs("p1", pair_limit=10, stats=stats)
    assert any("Failed deleting orphan row" in r.message for r in caplog.records)


# --- _flush_active_pairs ---------------------------------------------------


def _mem(project_deques=None):
    return SimpleNamespace(
        project_deques=project_deques if project_deques is not None else {},
        last_context_tokens_per_project={},
    )


def _patch_flush_active(monkeypatch, projects, *, flushed=1, rebuild_ok=True):
    mem = _mem({p.id: object() for p in projects})
    monkeypatch.setattr(cycle, "get_memory_manager", lambda: mem)
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(chat_history_limit_pairs=10))

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def exec(self, _q):
            return SimpleNamespace(all=lambda: list(projects))

    monkeypatch.setattr(cycle, "get_session", lambda: _S())
    monkeypatch.setattr(cycle, "_flush_project_pairs", lambda pid, pair_limit, stats: flushed)
    monkeypatch.setattr(cycle, "rebuild_daily_cache", lambda pid, reason=None: rebuild_ok)
    return mem


def test_flush_active_pairs_happy(monkeypatch):
    projects = [SimpleNamespace(id="p1", daily_rag_enabled=True)]
    _patch_flush_active(monkeypatch, projects)
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert stats.status == "success"


def test_flush_active_pairs_skips_disabled(monkeypatch):
    projects = [SimpleNamespace(id="p1", daily_rag_enabled=False)]
    _patch_flush_active(monkeypatch, projects)
    called = []
    monkeypatch.setattr(cycle, "_flush_project_pairs", lambda *a, **k: called.append(1) or 1)
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert called == []


def test_flush_active_pairs_rebuild_failure_partial(monkeypatch):
    projects = [SimpleNamespace(id="p1", daily_rag_enabled=True)]
    _patch_flush_active(monkeypatch, projects, rebuild_ok=False)
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert stats.status == "partial"
    assert any(e.startswith("daily_cache_rebuild:") for e in stats.errors)


def test_flush_active_pairs_cache_clear_failure_logged(monkeypatch, caplog):
    projects = [SimpleNamespace(id="p1", daily_rag_enabled=True)]
    mem = _patch_flush_active(monkeypatch, projects)

    class _BadDeques(dict):
        def __contains__(self, key):
            raise RuntimeError("deque boom")

    mem.project_deques = _BadDeques()
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert any("Failed clearing in-memory caches" in r.message for r in caplog.records)


def test_flush_active_pairs_per_project_failure_partial(monkeypatch):
    projects = [SimpleNamespace(id="p1", daily_rag_enabled=True)]
    _patch_flush_active(monkeypatch, projects)
    monkeypatch.setattr(
        cycle,
        "_flush_project_pairs",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("flush boom")),
    )
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert stats.status == "partial" and stats.projects_failed_count == 1


def test_flush_active_pairs_global_failure_partial(monkeypatch):
    monkeypatch.setattr(
        cycle, "get_memory_manager", lambda: (_ for _ in ()).throw(RuntimeError("mem boom"))
    )
    stats = cycle._SleepCycleStats()
    cycle._flush_active_pairs(stats)
    assert stats.status == "partial" and "flush:global" in stats.errors


# --- _backfill_daily_md ----------------------------------------------------


def test_backfill_daily_md_counts_updates(monkeypatch):
    monkeypatch.setattr(cycle, "backfill_daily_md_from_meta", lambda pid: True)
    stats = cycle._SleepCycleStats()
    cycle._backfill_daily_md([SimpleNamespace(id="p1"), SimpleNamespace(id="p2")], stats)
    assert stats.updated == 2


def test_backfill_daily_md_failure_partial(monkeypatch):
    monkeypatch.setattr(
        cycle,
        "backfill_daily_md_from_meta",
        lambda pid: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    stats = cycle._SleepCycleStats()
    cycle._backfill_daily_md([SimpleNamespace(id="p1")], stats)
    assert stats.status == "partial" and stats.projects_failed_count == 1


# --- _run_dream_and_auto_accept -------------------------------------------


def test_run_dream_disabled_auto_accept(monkeypatch):
    ran = []
    monkeypatch.setattr(cycle, "dream", lambda pid: ran.append(pid))
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(auto_accept_dreams=False))
    accepted = []
    monkeypatch.setattr(cycle, "auto_accept_dreams", lambda pid: accepted.append(pid))
    stats = cycle._SleepCycleStats()
    cycle._run_dream_and_auto_accept("p1", stats)
    assert ran == ["p1"] and accepted == []


def test_run_dream_failure_isolated(monkeypatch, caplog):
    monkeypatch.setattr(
        cycle, "dream", lambda pid: (_ for _ in ()).throw(RuntimeError("dream boom"))
    )
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(auto_accept_dreams=False))
    monkeypatch.setattr(cycle, "auto_accept_dreams", lambda pid: None)
    stats = cycle._SleepCycleStats()
    cycle._run_dream_and_auto_accept("p1", stats)
    assert any("[SLEEP][DREAM][ERROR]" in r.message for r in caplog.records)


def test_run_dream_auto_accept_success(monkeypatch):
    monkeypatch.setattr(cycle, "dream", lambda pid: None)
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(auto_accept_dreams=True))
    monkeypatch.setattr(
        cycle,
        "auto_accept_dreams",
        lambda pid: SimpleNamespace(
            failed=0,
            processed=2,
            accepted=2,
            filtered_remote_without_research=0,
            deleted_dream=True,
        ),
    )
    stats = cycle._SleepCycleStats()
    cycle._run_dream_and_auto_accept("p1", stats)
    assert stats.status == "success"


def test_run_dream_auto_accept_failure_partial(monkeypatch):
    monkeypatch.setattr(cycle, "dream", lambda pid: None)
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(auto_accept_dreams=True))
    monkeypatch.setattr(
        cycle,
        "auto_accept_dreams",
        lambda pid: SimpleNamespace(
            failed=1,
            processed=1,
            accepted=0,
            renamed_bad_path="/x",
            errors=["e"],
            filtered_remote_without_research=0,
            deleted_dream=False,
        ),
    )
    stats = cycle._SleepCycleStats()
    cycle._run_dream_and_auto_accept("p1", stats)
    assert stats.status == "partial" and any(
        e.startswith("dream_auto_accept:") for e in stats.errors
    )


def test_run_dream_auto_accept_raises_partial(monkeypatch):
    monkeypatch.setattr(cycle, "dream", lambda pid: None)
    monkeypatch.setattr(cycle, "get_settings", lambda: SimpleNamespace(auto_accept_dreams=True))
    monkeypatch.setattr(
        cycle, "auto_accept_dreams", lambda pid: (_ for _ in ()).throw(RuntimeError("aa boom"))
    )
    stats = cycle._SleepCycleStats()
    cycle._run_dream_and_auto_accept("p1", stats)
    assert stats.status == "partial"


# --- _post_merge_cleanup ---------------------------------------------------


def test_post_merge_cleanup_happy(tmp_path, monkeypatch):
    pid = "p1"
    base = tmp_path / pid
    base.mkdir()
    summary = base / "sleep_summary.md"
    summary.write_text("s", encoding="utf-8")
    dream_summary = base / "dream_summary.md"
    dream_summary.write_text("d", encoding="utf-8")
    meta = base / "daily.json"
    meta.write_text("{}", encoding="utf-8")
    md = base / "daily.md"
    md.write_text("md", encoding="utf-8")
    lock = base / "daily.lock"
    monkeypatch.setattr(cycle, "_project_daily_paths", lambda p: (str(meta), str(lock), str(md)))
    cleared = []
    monkeypatch.setattr(cycle, "clear_daily_cache", lambda p: cleared.append(p))
    cycle._post_merge_cleanup(pid, str(summary), str(dream_summary), has_dream_upload=True)
    assert not summary.exists() and not dream_summary.exists()
    assert not meta.exists() and not md.exists() and cleared == [pid]


def test_post_merge_cleanup_summary_remove_failure_logged(tmp_path, monkeypatch, caplog):
    pid = "p1"
    base = tmp_path / pid
    base.mkdir()
    meta = base / "daily.json"
    md = base / "daily.md"
    lock = base / "daily.lock"
    monkeypatch.setattr(cycle, "_project_daily_paths", lambda p: (str(meta), str(lock), str(md)))
    monkeypatch.setattr(cycle, "clear_daily_cache", lambda p: None)
    # summary_path does not exist -> os.remove raises -> logged, no abort.
    cycle._post_merge_cleanup(
        pid, str(base / "missing.md"), str(base / "nodream.md"), has_dream_upload=False
    )
    assert any("Failed removing summary" in r.message for r in caplog.records)


def test_post_merge_cleanup_clear_cache_failure_logged(tmp_path, monkeypatch, caplog):
    pid = "p1"
    base = tmp_path / pid
    base.mkdir()
    summary = base / "sleep_summary.md"
    summary.write_text("s", encoding="utf-8")
    meta = base / "daily.json"
    md = base / "daily.md"
    lock = base / "daily.lock"
    monkeypatch.setattr(cycle, "_project_daily_paths", lambda p: (str(meta), str(lock), str(md)))
    monkeypatch.setattr(
        cycle, "clear_daily_cache", lambda p: (_ for _ in ()).throw(RuntimeError("clear boom"))
    )
    cycle._post_merge_cleanup(pid, str(summary), str(base / "nodream.md"), has_dream_upload=False)
    assert any("Failed clearing in-memory daily cache" in r.message for r in caplog.records)


def test_post_merge_cleanup_inner_remove_failures_logged(tmp_path, monkeypatch, caplog):
    pid = "p1"
    base = tmp_path / pid
    base.mkdir()
    summary = base / "sleep_summary.md"
    summary.write_text("s", encoding="utf-8")
    dream_summary = base / "dream_summary.md"
    dream_summary.write_text("d", encoding="utf-8")
    meta = base / "daily.json"
    meta.write_text("{}", encoding="utf-8")
    md = base / "daily.md"
    md.write_text("md", encoding="utf-8")
    lock = base / "daily.lock"
    monkeypatch.setattr(cycle, "_project_daily_paths", lambda p: (str(meta), str(lock), str(md)))
    monkeypatch.setattr(cycle, "clear_daily_cache", lambda p: None)

    real_remove = cycle.os.remove

    def fake_remove(path):
        # Allow the summary removal; fail the dream_summary, daily.json, daily.md removals.
        if str(path).endswith(("dream_summary.md", "daily.json", "daily.md")):
            raise OSError("remove boom")
        return real_remove(path)

    monkeypatch.setattr(cycle.os, "remove", fake_remove)
    cycle._post_merge_cleanup(pid, str(summary), str(dream_summary), has_dream_upload=True)
    msgs = " ".join(r.message for r in caplog.records)
    assert "Failed removing dream_summary.md" in msgs
    assert "Failed removing daily.json" in msgs
    assert "Failed removing daily.md" in msgs


def test_post_merge_cleanup_outer_failure_logged(tmp_path, monkeypatch, caplog):
    pid = "p1"
    base = tmp_path / pid
    base.mkdir()
    summary = base / "sleep_summary.md"
    summary.write_text("s", encoding="utf-8")
    monkeypatch.setattr(
        cycle, "_project_daily_paths", lambda p: (_ for _ in ()).throw(RuntimeError("paths boom"))
    )
    cycle._post_merge_cleanup(pid, str(summary), str(base / "nodream.md"), has_dream_upload=False)
    assert any("Post-merge daily cleanup error" in r.message for r in caplog.records)


# --- _write_merge_artifacts_and_rebuild ------------------------------------


def _patch_merge(monkeypatch, tmp_path, *, verify_rag=False, rebuild_raises=False, load_ok=True):
    monkeypatch.setattr(
        cycle,
        "get_settings",
        lambda: SimpleNamespace(memory_root=str(tmp_path), verify_rag=verify_rag),
    )

    def _rebuild(pid):
        if rebuild_raises:
            raise RuntimeError("rebuild boom")

    monkeypatch.setattr(cycle, "rebuild_faiss_index", _rebuild)
    monkeypatch.setattr(cycle, "load_faiss_index", lambda pid: object() if load_ok else None)
    cleaned = []
    monkeypatch.setattr(cycle, "_post_merge_cleanup", lambda *a, **k: cleaned.append(a))
    return cleaned


def test_write_merge_skips_when_no_text(monkeypatch, tmp_path):
    cleaned = _patch_merge(monkeypatch, tmp_path)
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild("p1", "s.md", "d.md", "ts", "", "", stats)
    assert cleaned == [] and stats.status == "success"


def test_write_merge_writes_sleep_and_dream_and_cleans(monkeypatch, tmp_path):
    cleaned = _patch_merge(monkeypatch, tmp_path)
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild(
        "p1", "s.md", "d.md", "2026-01-01T00-00-00", "sleep body", "dream body", stats
    )
    sleep_dir = tmp_path / "p1" / "uploads" / "sleep"
    dream_dir = tmp_path / "p1" / "uploads" / "dream"
    assert any(f.name.startswith("sleep_") for f in sleep_dir.iterdir())
    assert any(f.name.startswith("dream_") for f in dream_dir.iterdir())
    assert len(cleaned) == 1


def test_write_merge_avoids_clobbering_existing_files(monkeypatch, tmp_path):
    cleaned = _patch_merge(monkeypatch, tmp_path)
    ts = "2026-01-01T00-00-00"
    base = tmp_path / "p1"
    sleep_dir = base / "uploads" / "sleep"
    dream_dir = base / "uploads" / "dream"
    sleep_dir.mkdir(parents=True)
    dream_dir.mkdir(parents=True)
    # Pre-create the would-be target names so the clobber-avoidance branch runs.
    (sleep_dir / f"sleep_{ts}.md").write_text("old", encoding="utf-8")
    (dream_dir / f"dream_{ts}.md").write_text("old", encoding="utf-8")
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild(
        "p1", "s.md", "d.md", ts, "sleep body", "dream body", stats
    )
    # Two files each now (original + the ns-suffixed alternate).
    assert len(list(sleep_dir.iterdir())) == 2
    assert len(list(dream_dir.iterdir())) == 2
    assert len(cleaned) == 1


def test_write_merge_verify_rag_pass_cleans(monkeypatch, tmp_path):
    cleaned = _patch_merge(monkeypatch, tmp_path, verify_rag=True, load_ok=True)
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild("p1", "s.md", "d.md", "ts", "sleep body", "", stats)
    assert len(cleaned) == 1


def test_write_merge_verify_rag_fail_skips_cleanup(monkeypatch, tmp_path):
    cleaned = _patch_merge(monkeypatch, tmp_path, verify_rag=True, load_ok=False)
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild("p1", "s.md", "d.md", "ts", "sleep body", "", stats)
    assert cleaned == []


def test_write_merge_rebuild_failure_partial(monkeypatch, tmp_path):
    _patch_merge(monkeypatch, tmp_path, rebuild_raises=True)
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild("p1", "s.md", "d.md", "ts", "sleep body", "", stats)
    assert stats.status == "partial" and any(e.startswith("merge:") for e in stats.errors)


def test_write_merge_legacy_lock_migration_failure_logged(monkeypatch, tmp_path, caplog):
    _patch_merge(monkeypatch, tmp_path)
    base = tmp_path / "p1"
    base.mkdir()
    # Legacy merge.lock present so the migration path runs; os.replace fails.
    (base / "merge.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        cycle.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    stats = cycle._SleepCycleStats()
    cycle._write_merge_artifacts_and_rebuild("p1", "s.md", "d.md", "ts", "sleep body", "", stats)
    assert any("merge lock migration failed" in r.message for r in caplog.records)


# --- _run_project_summary_pipeline -----------------------------------------


def _patch_pipeline(monkeypatch, tmp_path, **settings_kw):
    fields = {
        "memory_root": str(tmp_path),
        "verify_rag": False,
        "generate_debug_files": False,
        "auto_accept_dreams": False,
    }
    fields.update(settings_kw)
    settings = SimpleNamespace(**fields)
    monkeypatch.setattr(cycle, "get_settings", lambda: settings)
    monkeypatch.setattr(cycle, "consolidate_open_questions_artifact", lambda pid: None)
    monkeypatch.setattr(cycle, "normalize_legacy_artifact_wrappers", lambda text, **k: text)
    monkeypatch.setattr(cycle, "replace_current_scope_for_ltm", lambda text: text)
    monkeypatch.setattr(cycle, "_run_dream_and_auto_accept", lambda pid, stats: None)
    merged = []
    monkeypatch.setattr(
        cycle, "_write_merge_artifacts_and_rebuild", lambda *a, **k: merged.append(a)
    )
    return settings, merged


def test_pipeline_skips_when_no_daily(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, tmp_path)
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert stats.skipped_no_daily == 1 and stats.projects_processed == 0


def test_pipeline_consolidate_failure_logged_then_continues(monkeypatch, tmp_path, caplog):
    _patch_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cycle,
        "consolidate_open_questions_artifact",
        lambda pid: (_ for _ in ()).throw(RuntimeError("consol boom")),
    )
    (tmp_path / "p1").mkdir()
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert any("[SLEEP][QUESTIONS][WARN]" in r.message for r in caplog.records)


def test_pipeline_happy_writes_summary_and_merges(monkeypatch, tmp_path):
    _, merged = _patch_pipeline(monkeypatch, tmp_path)
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily content", encoding="utf-8")
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert stats.projects_processed == 1
    assert (base / "sleep_summary.md").read_text(encoding="utf-8") == "daily content"
    assert len(merged) == 1


def test_pipeline_daily_read_failure_returns(monkeypatch, tmp_path, caplog):
    _patch_pipeline(monkeypatch, tmp_path)
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    monkeypatch.setattr(
        cycle,
        "normalize_legacy_artifact_wrappers",
        lambda text, **k: (_ for _ in ()).throw(RuntimeError("norm boom")),
    )
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert any("Failed reading daily.md" in r.message for r in caplog.records)


def test_pipeline_consumes_dream_summary_with_debug(monkeypatch, tmp_path):
    _, merged = _patch_pipeline(monkeypatch, tmp_path, generate_debug_files=True)
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    (base / "dream_summary.md").write_text("dream stuff", encoding="utf-8")
    writes = []
    monkeypatch.setattr(cycle, "write_debug_file", lambda pid, name, body: writes.append(name))
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    # Dream upload text was prepared and merge invoked with it.
    assert merged and merged[0][5] == "dream stuff"
    assert "debug_dream_summary.txt" in writes


def test_pipeline_empty_summary_content_skips_merge(monkeypatch, tmp_path, caplog):
    _, merged = _patch_pipeline(monkeypatch, tmp_path)
    # normalize returns only boundary lines -> _summary_content_only empty -> skip.
    monkeypatch.setattr(cycle, "normalize_legacy_artifact_wrappers", lambda text, **k: "=== x ===")
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert merged == []
    assert any("[SLEEP][MERGE] Skipped (empty)" in r.message for r in caplog.records)


def test_pipeline_empty_summary_file_skips_merge(monkeypatch, tmp_path, caplog):
    _, merged = _patch_pipeline(monkeypatch, tmp_path)
    # normalize returns empty -> empty sleep_summary.md (size 0) -> merge skip.
    monkeypatch.setattr(cycle, "normalize_legacy_artifact_wrappers", lambda text, **k: "")
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert merged == []
    assert any("empty or missing sleep_summary.md" in r.message for r in caplog.records)


def test_pipeline_merge_and_dream_replace_failures_logged(monkeypatch, tmp_path, caplog):
    _, merged = _patch_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cycle,
        "replace_current_scope_for_ltm",
        lambda text: (_ for _ in ()).throw(RuntimeError("replace boom")),
    )
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    (base / "dream_summary.md").write_text("dream stuff", encoding="utf-8")
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    msgs = " ".join(r.message for r in caplog.records)
    assert "[SLEEP][MERGE][ERROR]" in msgs
    assert "[SLEEP][DREAM_SUMMARY][WARN]" in msgs
    # Both upload texts ended up None -> merge invoked but writes nothing.
    assert merged and merged[0][4] is None and merged[0][5] is None


def test_pipeline_dream_summary_debug_write_failure_logged(monkeypatch, tmp_path, caplog):
    _patch_pipeline(monkeypatch, tmp_path, generate_debug_files=True)
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    (base / "dream_summary.md").write_text("dream stuff", encoding="utf-8")
    monkeypatch.setattr(
        cycle,
        "write_debug_file",
        lambda pid, name, body: (_ for _ in ()).throw(RuntimeError("debug boom")),
    )
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert any("Failed writing debug file" in r.message for r in caplog.records)


def test_pipeline_outer_failure_partial(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, tmp_path)
    base = tmp_path / "p1"
    base.mkdir()
    (base / "daily.md").write_text("daily", encoding="utf-8")
    # Make the dream stage raise to trip the outer format except.
    monkeypatch.setattr(
        cycle,
        "_run_dream_and_auto_accept",
        lambda pid, stats: (_ for _ in ()).throw(RuntimeError("dream stage boom")),
    )
    stats = cycle._SleepCycleStats()
    cycle._run_project_summary_pipeline(SimpleNamespace(id="p1"), stats)
    assert stats.status == "partial" and any(e.startswith("format:") for e in stats.errors)
