"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for dream/sleep summary formatting.

Verifies ``collect_research_topics`` dedupes the first-seen valid research
topics (skipping non-dict items/entries), ``format_latest_sleep_summary``
appends (or omits) the research block, and ``write_latest_sleep_summary``
persists the card text best-effort (no-op when empty, warns on write failure).
"""
import app.utils.dream_summary as dream_summary
from app.utils.dream_summary import (
    collect_research_topics,
    format_latest_sleep_summary,
    write_latest_sleep_summary,
)


def test_collect_research_topics_dedupes_first_seen_valid_research():
    items = [
        {
            "research": [
                {"research_topic": "Topic A", "research_summary": "Summary A"},
                {"research_topic": "Topic B", "research_summary": "Summary B"},
            ]
        },
        {
            "research": [
                {"research_topic": "topic a", "research_summary": "Duplicate summary"},
                {"research_topic": "Topic C", "research_summary": ""},
            ]
        },
    ]

    assert collect_research_topics(items) == ["Topic A", "Topic B"]


def test_format_latest_sleep_summary_appends_research_block():
    text = format_latest_sleep_summary(
        "Project summary.",
        [
            {
                "research": [
                    {
                        "research_topic": "What memory architecture best supports long-term useful recall?",
                        "research_summary": "x",
                    },
                    {
                        "research_topic": "How should memory evolve over time?",
                        "research_summary": "y",
                    },
                ]
            }
        ],
    )

    assert text == (
        "Project summary.\n\n"
        "[RESEARCH]\n"
        "Topic: What memory architecture best supports long-term useful recall?\n\n"
        "Topic: How should memory evolve over time?\n"
    )


def test_collect_research_topics_skips_non_dict_items_and_entries():
    items = [
        "not-a-dict",
        {"research": ["also-not-a-dict", {"research_topic": "T", "research_summary": "S"}]},
    ]
    assert collect_research_topics(items) == ["T"]


def test_format_latest_sleep_summary_omits_empty_research_block():
    assert format_latest_sleep_summary("Project summary.", [{"research": []}]) == "Project summary."


def test_write_latest_sleep_summary_skips_blank_summary(tmp_path):
    write_latest_sleep_summary(
        project_id="p1", base_dir=str(tmp_path), project_summary="   ", accepted_items=[]
    )
    assert list(tmp_path.iterdir()) == []


def test_write_latest_sleep_summary_writes_card(tmp_path):
    write_latest_sleep_summary(
        project_id="p1",
        base_dir=str(tmp_path),
        project_summary="Project summary.",
        accepted_items=[{"research": [{"research_topic": "Topic A", "research_summary": "S"}]}],
    )
    out = tmp_path / "latest_sleep_summary.md"
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "Project summary." in body
    assert "[RESEARCH]" in body and "Topic: Topic A" in body
    assert body.endswith("\n")


def test_write_latest_sleep_summary_logs_on_write_failure(tmp_path, monkeypatch, caplog):
    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(dream_summary, "open", _boom, raising=False)
    with caplog.at_level("WARNING"):
        write_latest_sleep_summary(
            project_id="p1",
            base_dir=str(tmp_path),
            project_summary="Project summary.",
            accepted_items=[],
        )
    assert any("Failed writing latest dream summary" in r.message for r in caplog.records)
