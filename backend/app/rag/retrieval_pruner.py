"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Retrieval-specific pruning for RAG context snippets.

The pruner removes Syx artifact scaffolding from retrieved text immediately
before prompt assembly. It is intentionally separate from assistant-response
pruning so stored memory, tagger input behavior, and roll-off behavior remain
unchanged.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from ..pruning.light_response_pruner.similarity import prune_similar_sentences
from ..pruning.light_response_pruner.whitespace import compact_whitespace
from ..utils.tokens import count_tokens

_BOUNDARY_MARKER_RE = re.compile(
    r"^\s*<!--\s*(?:begin|end)\s+syx:memory_id=[^>]+-->\s*$",
    re.IGNORECASE,
)
_METADATA_HEADING_RE = re.compile(r"^\s*###\s+Syx Metadata\s*$", re.IGNORECASE)
_YAML_FENCE_RE = re.compile(r"^\s*```\s*yaml\s*$", re.IGNORECASE)
_CLOSING_FENCE_RE = re.compile(r"^\s*```\s*$")
_FRONT_MATTER_BOUNDARY_RE = re.compile(r"^\s*---\s*$")
_TOPICS_LIST_ITEM_RE = re.compile(r"^\s{2,}-\s+\S.*$")
_PLAIN_METADATA_LINE_RE = re.compile(
    r"^\s*(?:memory_id|entry_type|source|source_agent|source_scope|current_scope|"
    r"timestamp|route|keep|topics|intent|type|semantic_handle|day_sequence)\s*:",
    re.IGNORECASE,
)
_HASH_METADATA_LINE_RE = re.compile(
    r"^\s*#(?:timestamp|route|keep|topics|intent|type|semantic_handle)\s*:",
    re.IGNORECASE,
)
_SLEEP_DREAM_HEADING_RE = re.compile(r"^\s*#\s+(?:Dream Memory|Sleep Memory)\b.*$", re.IGNORECASE)
_ENTRY_HEADING_RE = re.compile(
    r"^\s*##\s+(?:Memory Entry|Chat Pair|Dream Output|Research|Question Answer|"
    r"Open Question|Idea|Sleep Summary|Dream Summary)(?::.*)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievalPruneResult:
    """Result of pruning one retrieved snippet.

    Attributes:
        pruned_text: Text after retrieval-specific cleanup.
        changed: Whether the text changed.
        metadata_blocks_removed: Count of Syx metadata blocks removed.
        metadata_lines_removed: Count of individual metadata lines removed.
        boundary_markers_removed: Count of Syx begin/end marker lines removed.
        entry_headings_removed: Count of generated artifact/entry headings removed.
        artifact_front_matter_blocks_removed: Count of Syx front matter blocks removed.
        whitespace_enabled: Whether whitespace compaction was enabled.
        similarity_enabled: Whether near-duplicate sentence pruning was enabled.
        similarity_threshold: Similarity threshold used for sentence pruning.
        similar_sentences_removed: Approximate count of sentences removed by
            the similarity stage.
        tokens_saved_structural: Token savings from structural Syx cleanup.
        tokens_saved_whitespace: Token savings from whitespace compaction.
        tokens_saved_similarity: Token savings from similarity pruning.
    """

    pruned_text: str
    changed: bool
    metadata_blocks_removed: int = 0
    metadata_lines_removed: int = 0
    boundary_markers_removed: int = 0
    entry_headings_removed: int = 0
    artifact_front_matter_blocks_removed: int = 0
    whitespace_enabled: bool = False
    similarity_enabled: bool = False
    similarity_threshold: int = 90
    similar_sentences_removed: int = 0
    tokens_saved_structural: int = 0
    tokens_saved_whitespace: int = 0
    tokens_saved_similarity: int = 0


@dataclass(frozen=True)
class RetrievalPruneTotals:
    """Aggregate retrieval-pruning counts for a batch of snippets."""

    changed: bool = False
    whitespace_enabled: bool = False
    similarity_enabled: bool = False
    similarity_threshold: int = 90
    metadata_blocks_removed: int = 0
    metadata_lines_removed: int = 0
    boundary_markers_removed: int = 0
    entry_headings_removed: int = 0
    artifact_front_matter_blocks_removed: int = 0
    similar_sentences_removed: int = 0
    tokens_saved_structural: int = 0
    tokens_saved_whitespace: int = 0
    tokens_saved_similarity: int = 0


def prune_retrieved_text(
    text: str,
    *,
    whitespace_enabled: bool = True,
    whitespace_mode: str = "preserve_code",
    similarity_enabled: bool = True,
    similarity_threshold: int = 90,
) -> RetrievalPruneResult:
    """Remove Syx scaffolding from one retrieved snippet.

    Args:
        text: Retrieved snippet body.
        whitespace_enabled: Whether to compact whitespace after structural cleanup.
        whitespace_mode: Retrieval whitespace mode. ``off`` disables compaction;
            other modes currently use the code-preserving compactor.
        similarity_enabled: Whether to remove near-duplicate prose sentences.
        similarity_threshold: Fuzzy threshold used for sentence dedupe.

    Returns:
        A structured result carrying the pruned text and removal counts.
    """
    original = str(text or "")
    structural = _prune_structural_syx_lines(original)
    pruned = structural.pruned_text

    original_tokens = _token_count(original)
    structural_tokens = _token_count(pruned)
    tokens_saved_structural = max(0, original_tokens - structural_tokens)

    effective_whitespace_enabled = (
        bool(whitespace_enabled) and str(whitespace_mode or "").strip() != "off"
    )
    before_whitespace_tokens = structural_tokens
    if effective_whitespace_enabled:
        pruned = compact_whitespace(pruned)
    after_whitespace_tokens = _token_count(pruned)
    tokens_saved_whitespace = max(0, before_whitespace_tokens - after_whitespace_tokens)

    before_similarity_text = pruned
    before_similarity_tokens = after_whitespace_tokens
    effective_similarity_enabled = bool(similarity_enabled)
    if effective_similarity_enabled:
        pruned = prune_similar_sentences(pruned, threshold=int(similarity_threshold)).strip()
    after_similarity_tokens = _token_count(pruned)
    tokens_saved_similarity = max(0, before_similarity_tokens - after_similarity_tokens)
    similar_sentences_removed = (
        max(0, _sentence_count(before_similarity_text) - _sentence_count(pruned))
        if effective_similarity_enabled
        else 0
    )

    return RetrievalPruneResult(
        pruned_text=pruned,
        changed=pruned != original,
        metadata_blocks_removed=structural.metadata_blocks_removed,
        metadata_lines_removed=structural.metadata_lines_removed,
        boundary_markers_removed=structural.boundary_markers_removed,
        entry_headings_removed=structural.entry_headings_removed,
        artifact_front_matter_blocks_removed=structural.artifact_front_matter_blocks_removed,
        whitespace_enabled=effective_whitespace_enabled,
        similarity_enabled=effective_similarity_enabled,
        similarity_threshold=int(similarity_threshold),
        similar_sentences_removed=similar_sentences_removed,
        tokens_saved_structural=tokens_saved_structural,
        tokens_saved_whitespace=tokens_saved_whitespace,
        tokens_saved_similarity=tokens_saved_similarity,
    )


def prune_retrieval_candidates(
    candidates: Iterable[Dict[str, Any]],
    *,
    whitespace_enabled: bool = True,
    whitespace_mode: str = "preserve_code",
    similarity_enabled: bool = True,
    similarity_threshold: int = 90,
) -> Tuple[List[Dict[str, Any]], RetrievalPruneTotals]:
    """Return candidates with pruned ``text`` values plus aggregate counts.

    Args:
        candidates: Retrieval candidate dicts. Each candidate is shallow-copied.
        whitespace_enabled: Whether to compact whitespace after structural cleanup.
        whitespace_mode: Retrieval whitespace mode.
        similarity_enabled: Whether to remove near-duplicate prose sentences.
        similarity_threshold: Fuzzy threshold used for sentence dedupe.

    Returns:
        Tuple of ``(pruned_candidates, totals)``.
    """
    out: List[Dict[str, Any]] = []
    totals = RetrievalPruneTotals()
    counts = {
        "changed": False,
        "whitespace_enabled": bool(whitespace_enabled)
        and str(whitespace_mode or "").strip() != "off",
        "similarity_enabled": bool(similarity_enabled),
        "similarity_threshold": int(similarity_threshold),
        "metadata_blocks_removed": 0,
        "metadata_lines_removed": 0,
        "boundary_markers_removed": 0,
        "entry_headings_removed": 0,
        "artifact_front_matter_blocks_removed": 0,
        "similar_sentences_removed": 0,
        "tokens_saved_structural": 0,
        "tokens_saved_whitespace": 0,
        "tokens_saved_similarity": 0,
    }

    for candidate in candidates or []:
        result = prune_retrieved_text(
            str(candidate.get("text") or ""),
            whitespace_enabled=whitespace_enabled,
            whitespace_mode=whitespace_mode,
            similarity_enabled=similarity_enabled,
            similarity_threshold=similarity_threshold,
        )
        cloned = dict(candidate)
        cloned["text"] = result.pruned_text
        out.append(cloned)
        counts["changed"] = bool(counts["changed"] or result.changed)
        counts["metadata_blocks_removed"] += int(result.metadata_blocks_removed)
        counts["metadata_lines_removed"] += int(result.metadata_lines_removed)
        counts["boundary_markers_removed"] += int(result.boundary_markers_removed)
        counts["entry_headings_removed"] += int(result.entry_headings_removed)
        counts["artifact_front_matter_blocks_removed"] += int(
            result.artifact_front_matter_blocks_removed
        )
        counts["similar_sentences_removed"] += int(result.similar_sentences_removed)
        counts["tokens_saved_structural"] += int(result.tokens_saved_structural)
        counts["tokens_saved_whitespace"] += int(result.tokens_saved_whitespace)
        counts["tokens_saved_similarity"] += int(result.tokens_saved_similarity)

    totals = RetrievalPruneTotals(**counts)
    return out, totals


def _prune_structural_syx_lines(text: str) -> RetrievalPruneResult:
    """Remove Syx structural lines while preserving content headings."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    out: List[str] = []
    idx = 0
    counts = {
        "metadata_blocks_removed": 0,
        "metadata_lines_removed": 0,
        "boundary_markers_removed": 0,
        "entry_headings_removed": 0,
        "artifact_front_matter_blocks_removed": 0,
    }

    while idx < len(lines):
        line = lines[idx]
        front_matter_end = _syx_front_matter_end(lines, idx)
        if front_matter_end is not None:
            counts["artifact_front_matter_blocks_removed"] += 1
            idx = front_matter_end + 1
            continue

        if _BOUNDARY_MARKER_RE.match(line):
            counts["boundary_markers_removed"] += 1
            idx += 1
            continue

        if _METADATA_HEADING_RE.match(line):
            next_idx, removed_lines = _consume_metadata_block(lines, idx)
            counts["metadata_blocks_removed"] += 1
            counts["metadata_lines_removed"] += removed_lines
            idx = next_idx
            continue

        if _is_generated_heading(line):
            counts["entry_headings_removed"] += 1
            idx += 1
            continue

        if _is_metadata_line(line):
            counts["metadata_lines_removed"] += 1
            idx += 1
            if _is_topics_line(line):
                while idx < len(lines) and _TOPICS_LIST_ITEM_RE.match(lines[idx]):
                    counts["metadata_lines_removed"] += 1
                    idx += 1
            continue

        out.append(line)
        idx += 1

    pruned = "\n".join(out).strip()
    return RetrievalPruneResult(
        pruned_text=pruned,
        changed=pruned != str(text or ""),
        **counts,
    )


def _token_count(text: str) -> int:
    """Return a safe token count for pruning telemetry."""
    return int(count_tokens(text or ""))


def _sentence_count(text: str) -> int:
    """Count simple prose sentence endings for similarity-pruning telemetry."""
    if not str(text or "").strip():
        return 0
    return len(re.findall(r"[.!?](?=\s|$)", str(text)))


def _consume_metadata_block(lines: List[str], start_idx: int) -> Tuple[int, int]:
    """Return the index after a Syx metadata block and removed line count."""
    idx = start_idx + 1
    removed = 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
        removed += 1
    if idx < len(lines) and _YAML_FENCE_RE.match(lines[idx]):
        idx += 1
        removed += 1
        while idx < len(lines):
            removed += 1
            if _CLOSING_FENCE_RE.match(lines[idx]):
                idx += 1
                return idx, removed
            idx += 1
        return idx, removed

    while idx < len(lines) and (
        _is_metadata_line(lines[idx]) or _TOPICS_LIST_ITEM_RE.match(lines[idx])
    ):
        idx += 1
        removed += 1
    return idx, removed


def _syx_front_matter_end(lines: List[str], start_idx: int) -> int | None:
    """Return closing index for a Syx artifact front matter block, if present."""
    if not _FRONT_MATTER_BOUNDARY_RE.match(lines[start_idx]):
        return None
    end = start_idx + 1
    while end < len(lines):
        if _FRONT_MATTER_BOUNDARY_RE.match(lines[end]):
            body = "\n".join(lines[start_idx + 1 : end]).lower()
            if "syx_artifact_type:" in body and any(
                key in body for key in ("project_id:", "memory_date:", "format_version:")
            ):
                return end
            return None
        end += 1
    return None


def _is_metadata_line(line: str) -> bool:
    return bool(_PLAIN_METADATA_LINE_RE.match(line) or _HASH_METADATA_LINE_RE.match(line))


def _is_topics_line(line: str) -> bool:
    stripped = line.strip().lower()
    return stripped.startswith("topics:") or stripped.startswith("#topics:")


def _is_generated_heading(line: str) -> bool:
    return bool(_SLEEP_DREAM_HEADING_RE.match(line) or _ENTRY_HEADING_RE.match(line))
