"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
from backend.app.rag.syx_memory_artifact import (
    ensure_blank_line_before_begin_markers,
    ensure_entry_headings,
    generate_memory_id,
    parse_syx_entries,
    render_memory_entry,
    replace_current_scope_for_ltm,
    snake_case_value,
    validate_syx_boundaries,
)


def test_parse_valid_entry_with_nested_markdown():
    memory_id = generate_memory_id(
        project_id="project",
        timestamp="05-07-2026_21:42:00",
        source="chat",
        entry_type="chat_pair",
        user_text="# user heading",
        assistant_text="```python\nprint('ok')\n```",
    )
    text = render_memory_entry(
        memory_id=memory_id,
        metadata={
            "memory_id": memory_id,
            "entry_type": "chat_pair",
            "source": "chat",
            "source_scope": "daily",
            "current_scope": "daily",
            "topics": ["Syx", "markdown"],
        },
        user_text="# user heading",
        assistant_text="```python\nprint('ok')\n```",
    )

    parsed = parse_syx_entries(text)

    assert parsed.warnings == []
    assert len(parsed.entries) == 1
    assert parsed.entries[0].memory_id == memory_id
    assert parsed.entries[0].metadata["topics"] == ["Syx", "markdown"]
    assert "```python" in parsed.entries[0].text


def test_validate_reports_malformed_and_duplicate_entries():
    first = "mem_20260507_214200_a8f3"
    duplicate = (
        f"<!-- begin syx:memory_id={first} -->\nbody\n<!-- end syx:memory_id={first} -->\n"
        f"<!-- begin syx:memory_id={first} -->\nbody2\n<!-- end syx:memory_id={first} -->\n"
    )
    ok, warnings = validate_syx_boundaries(duplicate)

    assert ok is False
    assert any("duplicate memory_id" in warning for warning in warnings)

    malformed = f"<!-- begin syx:memory_id={first} -->\nbody\n"
    ok, warnings = validate_syx_boundaries(malformed)
    assert ok is False
    assert any("begin without end" in warning for warning in warnings)


def test_replace_current_scope_for_ltm_updates_dream_scope():
    chat_id = "mem_20260507_214200_a8f3"
    dream_id = "mem_20260507_214201_b8f3"
    chat = render_memory_entry(
        memory_id=chat_id,
        metadata={
            "memory_id": chat_id,
            "entry_type": "chat_pair",
            "source": "chat",
            "current_scope": "daily",
        },
        user_text="u",
        assistant_text="a",
    )
    dream = render_memory_entry(
        memory_id=dream_id,
        metadata={
            "memory_id": dream_id,
            "entry_type": "dream_output",
            "source": "dream",
            "source_scope": "dream",
            "current_scope": "dream",
        },
        user_text="u",
        assistant_text="a",
    )

    rewritten = replace_current_scope_for_ltm(chat + dream)

    assert rewritten.count("current_scope: ltm") == 2
    assert "source_scope: dream" in rewritten
    assert "current_scope: dream" not in rewritten


def test_rendered_entries_have_blank_line_between_begin_markers():
    first_id = "mem_20260507_214200_a8f3"
    second_id = "mem_20260507_214201_b8f3"
    first = render_memory_entry(
        memory_id=first_id,
        metadata={"memory_id": first_id, "entry_type": "chat_pair"},
        user_text="one",
        assistant_text="two",
    )
    second = render_memory_entry(
        memory_id=second_id,
        metadata={"memory_id": second_id, "entry_type": "chat_pair"},
        user_text="three",
        assistant_text="four",
    )

    normalized = ensure_blank_line_before_begin_markers(first.rstrip() + "\n" + second)

    assert f"<!-- end syx:memory_id={first_id} -->\n\n<!-- begin syx:memory_id={second_id} -->" in normalized


def test_snake_case_value_normalizes_human_labels():
    assert snake_case_value("Open Question") == "open_question"
    assert snake_case_value("answer_remote") == "answer_remote"
    assert snake_case_value("New Topic / Insight") == "new_topic_insight"


def test_rendered_entry_includes_semantic_handle_heading():
    memory_id = "mem_20260507_214200_a8f3"
    text = render_memory_entry(
        memory_id=memory_id,
        metadata={
            "memory_id": memory_id,
            "entry_type": "dream_output",
            "semantic_handle": "assessing whether a retrieved memory actually helped",
        },
        user_text="u",
        assistant_text="a",
    )

    assert (
        "<!-- begin syx:memory_id=mem_20260507_214200_a8f3 -->\n"
        "## Dream Output: assessing whether a retrieved memory actually helped\n\n"
        "### Syx Metadata"
    ) in text


def test_ensure_entry_headings_uses_legacy_semantic_handle():
    memory_id = "mem_20260507_214200_a8f3"
    text = (
        f"<!-- begin syx:memory_id={memory_id} -->\n"
        "#timestamp: 05-07-2026_21:42:00\n"
        "#semantic_handle: legacy topic handle\n\n"
        "body\n"
        f"<!-- end syx:memory_id={memory_id} -->\n"
    )

    normalized = ensure_entry_headings(text)

    assert "## Memory Entry: legacy topic handle" in normalized
