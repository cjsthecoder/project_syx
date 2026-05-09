"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""

from pathlib import Path

from tools.tag_legacy_syx_boundaries import _infer_project_id, tag_text


def test_legacy_boundary_tagger_wraps_blocks_idempotently():
    legacy = (
        "=== BEGIN DAILY PAIR ===\n"
        "#timestamp: 05-07-2026_21:42:00\n"
        "#route: other\n"
        "\n"
        "--- USER (data-message-author-role: user) ---\n"
        "hello\n"
        "\n"
        "*** ASSISTANT (data-message-author-role: assistant) ***\n"
        "hi\n"
        "\n"
        "=== END DAILY PAIR ===\n"
    )

    tagged, changed, warnings = tag_text(legacy, project_id="project")
    tagged_again, changed_again, warnings_again = tag_text(tagged, project_id="project")

    assert changed >= 1
    assert warnings == []
    assert "syx_artifact_type: daily_memory" in tagged
    assert "<!-- begin syx:memory_id=mem_20260507_214200_" in tagged
    assert "=== BEGIN DAILY PAIR ===" not in tagged
    assert "=== END DAILY PAIR ===" not in tagged
    assert tagged_again == tagged
    assert changed_again == 0
    assert warnings_again == []


def test_legacy_boundary_tagger_skips_malformed_pair_without_timestamp():
    legacy = "=== BEGIN DAILY PAIR ===\nno timestamp\n=== END DAILY PAIR ===\n"

    tagged, changed, warnings = tag_text(legacy, project_id="project")

    assert "syx_artifact_type: daily_memory" in tagged
    assert "no timestamp" in tagged
    assert changed == 1
    assert any("without #timestamp" in warning for warning in warnings)


def test_infer_project_id_from_memory_path():
    path = Path("/repo/data/memory/project-123/uploads/sleep/sleep.md")

    assert _infer_project_id(path) == "project-123"


def test_legacy_boundary_tagger_strips_delimiters_from_existing_wrapped_block():
    text = (
        "<!-- begin syx:memory_id=mem_20260507_214200_a8f3 -->\n"
        "=== BEGIN DREAM PAIR ===\n"
        "#timestamp: 05-07-2026_21:42:00\n"
        "body\n"
        "=== END DREAM PAIR ===\n"
        "<!-- end syx:memory_id=mem_20260507_214200_a8f3 -->\n"
    )

    tagged, changed, warnings = tag_text(text, project_id="project")

    assert changed > 0
    assert warnings == []
    assert "syx_artifact_type: daily_memory" in tagged
    assert "=== BEGIN DREAM PAIR ===" not in tagged
    assert "=== END DREAM PAIR ===" not in tagged
    assert "#timestamp: 05-07-2026_21:42:00" in tagged


def test_legacy_boundary_tagger_normalizes_dream_output_type():
    text = (
        "---\n"
        "syx_artifact_type: dream_memory\n"
        "project_id: project\n"
        "memory_date: 05-07-2026\n"
        "format_version: 1\n"
        "---\n\n"
        "# Dream Memory: 05-07-2026\n\n"
        "dream_output_type: Open Question\n"
    )

    tagged, changed, warnings = tag_text(text, project_id="project", artifact_type="dream_memory")

    assert changed == 1
    assert warnings == []
    assert "dream_output_type: open_question" in tagged


def test_legacy_boundary_tagger_adds_entry_heading_from_yaml_semantic_handle():
    text = (
        "---\n"
        "syx_artifact_type: dream_memory\n"
        "project_id: project\n"
        "memory_date: 05-07-2026\n"
        "format_version: 1\n"
        "---\n\n"
        "# Dream Memory: 05-07-2026\n\n"
        "<!-- begin syx:memory_id=mem_20260507_214200_a8f3 -->\n"
        "### Syx Metadata\n\n"
        "```yaml\n"
        "memory_id: mem_20260507_214200_a8f3\n"
        "entry_type: dream_output\n"
        "semantic_handle: useful memory attribution\n"
        "```\n\n"
        "body\n"
        "<!-- end syx:memory_id=mem_20260507_214200_a8f3 -->\n"
    )

    tagged, changed, warnings = tag_text(text, project_id="project", artifact_type="dream_memory")

    assert changed == 1
    assert warnings == []
    assert "## Dream Output: useful memory attribution" in tagged
