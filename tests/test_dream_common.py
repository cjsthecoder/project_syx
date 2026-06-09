"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.dream.common pure helpers.

Covers origin-id collection, resolution normalization, research filtering
(count and detailed-row forms), pair expansion, tag-block formatting (including
the defensive formatting failure), and markdown-block metadata assembly.
"""

from app.dream import common


def test_origin_memory_ids_collects_top_level_and_metadata():
    item = {
        "origin_memory_id": " a ",
        "memory_id": "b",
        "metadata": {
            "memory_id": "c",
            "origin_memory_ids": ["d", " e ", "", None],
        },
    }
    assert common.origin_memory_ids(item) == ["a", "b", "c", "d", "e"]


def test_origin_memory_ids_empty_when_absent():
    assert common.origin_memory_ids({"metadata": "not-a-dict"}) == []


def test_normalize_resolution():
    assert common.normalize_resolution("ANSWER_LOCAL") == "answer_local"
    assert common.normalize_resolution("bogus") == ""
    assert common.normalize_resolution(None) == ""


def test_valid_research_entries_filters_incomplete_and_non_dict():
    item = {
        "research": [
            {"research_topic": "t1", "research_summary": "s1"},
            {"research_topic": "", "research_summary": "s2"},  # missing topic
            {"research_topic": "t3", "research_summary": ""},  # missing summary
            "not-a-dict",
        ]
    }
    assert common.valid_research_entries(item) == [
        {"research_topic": "t1", "research_summary": "s1"}
    ]


def test_dream_memory_pairs_remote_expands_per_research():
    item = {
        "source_resolution": "answer_remote",
        "research": [
            {"research_topic": "t1", "research_summary": "s1"},
            {"research_topic": "t2", "research_summary": "s2"},
        ],
    }
    pairs = common.dream_memory_pairs_for_item(item)
    assert [p["user_text"] for p in pairs] == ["t1", "t2"]
    assert pairs[0]["assistant_text"].startswith("[RESEARCH]")


def test_dream_memory_pairs_local_single_pair_with_fallback_summary():
    item = {"source_resolution": "answer_local", "origin_text": "q"}
    pairs = common.dream_memory_pairs_for_item(item)
    assert pairs == [{"item": item, "user_text": "q", "assistant_text": "(no summary)"}]


def test_filter_remote_without_research_drops_remote_without_research():
    items = [
        {"source_resolution": "answer_local", "origin_text": "keep"},
        {"source_resolution": "answer_remote", "research": []},  # dropped
        "not-a-dict",  # skipped
    ]
    kept, dropped = common.filter_remote_without_research(items)
    assert dropped == 1
    assert [it["origin_text"] for it in kept] == ["keep"]


def test_filter_remote_without_research_with_rows_details_dropped():
    items = [
        {"source_resolution": "answer_local", "origin_text": "local-keep"},  # non-remote kept as-is
        {
            "source_resolution": "answer_remote",
            "research": [{"research_topic": "t", "research_summary": "s"}],
        },
        {"id": "x9", "source_resolution": "answer_remote", "origin_text": "o", "research": []},
        "not-a-dict",
    ]
    kept, dropped_rows = common.filter_remote_without_research_with_rows(items)
    assert len(kept) == 2
    assert dropped_rows == [
        {
            "id": "x9",
            "origin_text": "o",
            "source_resolution": "answer_remote",
            "research_count": 0,
            "reason": "remote_without_research",
        }
    ]


def test_format_tags_block_renders_lines():
    block = common.format_tags_block(
        {"topics": "a,b", "intent": "learn", "type": "fact", "semantic_handle": "h"}
    )
    assert "#topics: a,b" in block and "#semantic_handle: h" in block


def test_format_tags_block_non_dict_returns_empty():
    assert common.format_tags_block("nope") == ""


def test_format_tags_block_swallows_formatting_error(caplog):
    class _BadStr:
        def __str__(self):
            raise RuntimeError("str boom")

    # semantic_handle's str() raises inside the try -> defensive empty fallback.
    assert common.format_tags_block({"topics": "t", "semantic_handle": _BadStr()}) == ""
    assert any("failed formatting tags block" in r.message for r in caplog.records)


def test_dream_markdown_block_includes_metadata():
    item = {
        "id": "item-1",
        "origin_type": "Open Question",
        "origin_memory_id": "m1",
    }
    block = common.dream_markdown_block(
        memory_id="mem_1",
        timestamp="2026/06/09",
        route="EXPLORATORY",
        keep=True,
        tags_meta={"topics": "alpha", "semantic_handle": "h"},
        item=item,
        user_text="u",
        assistant_text="a",
    )
    assert "mem_1" in block and "u" in block and "a" in block
