"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for retrieval-only RAG context pruning.

These cover Syx scaffold cleanup before prompt assembly while preserving useful
retrieved content headings.
"""

from app.rag.retrieval_pruner import prune_retrieval_candidates, prune_retrieved_text


def test_prune_retrieved_text_removes_syx_boundaries_metadata_and_headings():
    text = """<!-- begin syx:memory_id=mem_20260610_182007_bb74e748 -->
## Chat Pair: authentication cleanup

### Syx Metadata

```yaml
memory_id: mem_20260610_182007_bb74e748
entry_type: chat_pair
topics:
  - auth
  - cleanup
semantic_handle: auth cleanup
```

### User Message
What changed?

### Assistant Message
Useful answer remains.
<!-- end syx:memory_id=mem_20260610_182007_bb74e748 -->"""

    result = prune_retrieved_text(text, whitespace_enabled=False, similarity_enabled=False)

    assert "begin syx" not in result.pruned_text
    assert "end syx" not in result.pruned_text
    assert "### Syx Metadata" not in result.pruned_text
    assert "memory_id:" not in result.pruned_text
    assert "## Chat Pair" not in result.pruned_text
    assert "Useful answer remains." in result.pruned_text
    assert result.metadata_blocks_removed == 1
    assert result.boundary_markers_removed == 2
    assert result.entry_headings_removed == 1


def test_prune_retrieved_text_removes_chopped_metadata_lines_and_topic_items():
    text = """topics:
  - timing-sensitive reinforcement
  - eligibility traces
intent: ask for explanation
Real markdown list:
  - keep this item
content after metadata"""

    result = prune_retrieved_text(text, whitespace_enabled=False, similarity_enabled=False)

    assert "topics:" not in result.pruned_text
    assert "timing-sensitive reinforcement" not in result.pruned_text
    assert "intent:" not in result.pruned_text
    assert "Real markdown list:" in result.pruned_text
    assert "  - keep this item" in result.pruned_text
    assert "content after metadata" in result.pruned_text


def test_prune_retrieved_text_removes_sleep_dream_scaffold_but_keeps_research_headings():
    text = """---
syx_artifact_type: dream_memory
project_id: ce667335-ae8e-41d7-b810-59627cd8d67a
memory_date: 05-07-2026
format_version: 1
---
# Dream Memory 05-07-2026
## Memory Entry: timing research
#timestamp: 05-07-2026_13:23:01
#route: other
#topics: timing-sensitive reinforcement, eligibility traces
#intent: ask for explanation
#type: research
#semantic_handle: timing-sensitive reinforcement for memory selection
[RESEARCH]
### Key findings
Useful finding.
### Conditions / assumptions
Useful assumption.
### Limitations / risks
Useful risk."""

    result = prune_retrieved_text(text, similarity_enabled=False)

    assert "syx_artifact_type:" not in result.pruned_text
    assert "# Dream Memory" not in result.pruned_text
    assert "## Memory Entry" not in result.pruned_text
    assert "#timestamp:" not in result.pruned_text
    assert "[RESEARCH]" in result.pruned_text
    assert "### Key findings" in result.pruned_text
    assert "### Conditions / assumptions" in result.pruned_text
    assert "### Limitations / risks" in result.pruned_text
    assert result.artifact_front_matter_blocks_removed == 1
    assert result.entry_headings_removed == 2


def test_prune_retrieval_candidates_shallow_copies_and_aggregates_counts():
    original = [{"source": "ltm", "text": "memory_id: x\nUseful", "metadata": {"filename": "f.md"}}]

    pruned, totals = prune_retrieval_candidates(original, similarity_enabled=False)

    assert pruned is not original
    assert pruned[0] is not original[0]
    assert original[0]["text"] == "memory_id: x\nUseful"
    assert pruned[0]["text"] == "Useful"
    assert totals.changed is True
    assert totals.metadata_lines_removed == 1
    assert totals.tokens_saved_structural > 0
    assert totals.similarity_enabled is False


def test_prune_retrieved_text_reports_similarity_stage_counts():
    text = (
        "The retrieval context repeats the same idea. "
        "The retrieval context repeats the same idea. "
        "A different sentence remains."
    )

    result = prune_retrieved_text(
        text,
        whitespace_enabled=False,
        similarity_enabled=True,
        similarity_threshold=90,
    )

    assert result.similarity_enabled is True
    assert result.similarity_threshold == 90
    assert result.similar_sentences_removed == 1
    assert result.tokens_saved_similarity > 0
    assert result.pruned_text.count("The retrieval context repeats the same idea.") == 1
