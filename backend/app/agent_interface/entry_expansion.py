"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""A.5 full-entry expansion for agent memory search snippets."""

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..core.config import get_settings
from ..rag.manager_index_io import LTM_DOCSTORE_NAME, safe_load_json
from ..rag.syx_memory_artifact import normalize_lf, parse_syx_entries
from .models import AgentMemorySnippet

logger = logging.getLogger(__name__)

TRUNCATION_NOTICE = (
    "[TRUNCATED: entry content omitted because the serialized agent memory snippet "
    "exceeded AGENT_MEMORY_MAX_ENTRY_CHARS.]"
)


@dataclass(frozen=True)
class _ExpansionResult:
    """Outcome of expanding a single bounded snippet to its full entry text."""

    text: str
    status: str
    method: str
    error: Optional[str] = None
    warning: Optional[str] = None


def expand_agent_memory_snippets(
    *,
    project_id: str,
    snippets: List[AgentMemorySnippet],
    max_serialized_chars: Optional[int] = None,
) -> List[AgentMemorySnippet]:
    """Expand bounded snippets to full Syx entries while preserving A.4 ordering.

    Non-bounded snippets are passed through marked ``not_applicable``. Bounded
    snippets are expanded in place (text and ``entry_expansion_*`` fields set)
    and deduplicated by ``memory_id``, keeping the first occurrence. Oversized
    expansions are truncated to honor the serialized size limit.

    Args:
        project_id: Project whose memory artifacts/docstore are read.
        snippets: Parsed snippets to expand, in A.4 retrieval order.
        max_serialized_chars: Optional override for the maximum serialized
            snippet size; falls back to ``AGENT_MEMORY_MAX_ENTRY_CHARS`` (and to
            ``25000`` when that setting is invalid).

    Returns:
        The expanded snippets in their original order, with duplicates by
        ``memory_id`` removed.
    """
    try:
        configured_limit = int(max_serialized_chars or get_settings().agent_memory_max_entry_chars)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "agent_memory_expand invalid max chars; project_id=%s detail=%s",
            project_id,
            exc,
        )
        configured_limit = 25_000
    max_chars = max(1, int(configured_limit))

    out: List[AgentMemorySnippet] = []
    seen_memory_ids: set[str] = set()
    for snippet in snippets or []:
        if snippet.result_mode != "bounded_entry" or not snippet.memory_id:
            snippet.entry_expansion_status = "not_applicable"
            snippet.entry_expansion_method = "not_applicable"
            out.append(snippet)
            continue

        memory_id = str(snippet.memory_id).strip()
        if memory_id in seen_memory_ids:
            continue
        seen_memory_ids.add(memory_id)

        result = _expand_one(project_id=project_id, snippet=snippet)
        snippet.text = result.text
        snippet.entry_expansion_status = result.status
        snippet.entry_expansion_method = result.method
        if result.error:
            snippet.entry_expansion_error = result.error
        if result.warning:
            snippet.entry_expansion_warning = result.warning
        _apply_size_guard(
            snippet, max_chars=max_chars, artifact_expansion=result.status == "expanded"
        )
        out.append(snippet)
    return out


def _expand_one(*, project_id: str, snippet: AgentMemorySnippet) -> _ExpansionResult:
    """Expand a single bounded snippet to its full entry text.

    Tries, in order: the artifact path boundary, the source_document_id path
    boundary, docstore reconstruction, and finally the original snippet text.
    Path mismatches and failures are surfaced via the result's warning/error
    fields rather than raised.

    Args:
        project_id: Project whose uploads/docstore are searched.
        snippet: Bounded snippet to expand; its paths and ``memory_id`` drive
            the lookup strategy.

    Returns:
        An ``_ExpansionResult`` whose ``status`` reflects the strategy used
        (``expanded``, ``fallback``, or ``failed``) and whose ``method`` names
        the source; the ``error``/``warning`` fields carry non-fatal detail.
    """
    artifact_path = _clean_upload_relative_path(
        snippet.artifact_path,
        project_id=project_id,
        memory_id=snippet.memory_id,
        snippet_number=snippet.snippet_number,
        field="artifact_path",
    )
    source_path_raw = _path_from_source_document_id(snippet.source_document_id)
    source_path = _clean_upload_relative_path(
        source_path_raw,
        project_id=project_id,
        memory_id=snippet.memory_id,
        snippet_number=snippet.snippet_number,
        field="source_document_id",
    )
    mismatch_warning: Optional[str] = None
    if artifact_path and source_path and artifact_path != source_path:
        mismatch_warning = "artifact_path_source_document_id_mismatch"
        logger.warning(
            "agent_memory_expand artifact path mismatch; project_id=%s snippet_number=%s memory_id=%s artifact_path=%s source_document_id_path=%s",
            project_id,
            snippet.snippet_number,
            snippet.memory_id,
            artifact_path,
            source_path,
        )

    if artifact_path:
        expanded, error = _extract_from_artifact(
            project_id, artifact_path, str(snippet.memory_id), snippet.snippet_number
        )
        if expanded is not None:
            return _ExpansionResult(
                text=expanded,
                status="expanded",
                method="artifact_path_boundary",
                warning=mismatch_warning,
            )
    else:
        error = "artifact_path_unavailable"

    if source_path and source_path != artifact_path:
        expanded, source_error = _extract_from_artifact(
            project_id,
            source_path,
            str(snippet.memory_id),
            snippet.snippet_number,
        )
        if expanded is not None:
            return _ExpansionResult(
                text=expanded,
                status="expanded",
                method="source_document_id_boundary",
                warning=mismatch_warning,
            )
        error = source_error or error

    reconstructed = _reconstruct_from_docstore(
        project_id=project_id, source_document_id=snippet.source_document_id
    )
    if reconstructed:
        return _ExpansionResult(
            text=reconstructed,
            status="fallback",
            method="docstore_reconstruction",
            error=error or "artifact_boundary_extraction_failed",
            warning=mismatch_warning,
        )

    if snippet.text:
        return _ExpansionResult(
            text=snippet.text,
            status="fallback",
            method="original_snippet",
            error=error or "full_entry_expansion_failed",
            warning=mismatch_warning,
        )

    return _ExpansionResult(
        text="",
        status="failed",
        method="original_snippet",
        error=error or "full_entry_expansion_failed",
        warning=mismatch_warning,
    )


def _extract_from_artifact(
    project_id: str,
    upload_relative_path: str,
    memory_id: str,
    snippet_number: int,
) -> Tuple[Optional[str], Optional[str]]:
    """Extract a memory entry's text from an uploaded artifact file.

    Reads the artifact (rejecting paths that escape the uploads directory),
    parses Syx entries, and returns the entry matching ``memory_id``.

    Args:
        project_id: Project whose uploads directory roots the lookup.
        upload_relative_path: Artifact path relative to the uploads directory.
        memory_id: Memory entry id to locate within the parsed artifact.
        snippet_number: Snippet ordinal, used only for log context.

    Returns:
        A ``(text, error)`` tuple. On success ``text`` is the entry text and
        ``error`` is ``None``; on failure ``text`` is ``None`` and ``error`` is
        a short reason code (e.g. ``unsafe_artifact_path``,
        ``artifact_read_failed``, ``memory_id_boundary_not_found``).
    """
    base = _uploads_dir(project_id)
    path = os.path.abspath(os.path.join(base, upload_relative_path))
    if not _is_within(path, base):
        logger.warning(
            "agent_memory_expand rejected escaped artifact path; project_id=%s snippet_number=%s memory_id=%s path=%s",
            project_id,
            snippet_number,
            memory_id,
            upload_relative_path,
        )
        return None, "unsafe_artifact_path"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        logger.warning(
            "agent_memory_expand artifact read failed; project_id=%s snippet_number=%s memory_id=%s path=%s detail=%s",
            project_id,
            snippet_number,
            memory_id,
            upload_relative_path,
            exc,
        )
        return None, "artifact_read_failed"

    normalized = normalize_lf(text)
    parsed = parse_syx_entries(normalized, artifact_path=upload_relative_path)
    for warning in parsed.warnings:
        if "duplicate memory_id" in warning and memory_id in warning:
            logger.warning(
                "agent_memory_expand duplicate memory_id boundaries; project_id=%s snippet_number=%s memory_id=%s path=%s detail=%s",
                project_id,
                snippet_number,
                memory_id,
                upload_relative_path,
                warning,
            )
    matches = [entry for entry in parsed.entries if entry.memory_id == memory_id]
    if not matches:
        return None, "memory_id_boundary_not_found"
    if len(matches) > 1:
        logger.warning(
            "agent_memory_expand duplicate memory_id boundaries; project_id=%s snippet_number=%s memory_id=%s path=%s count=%s",
            project_id,
            snippet_number,
            memory_id,
            upload_relative_path,
            len(matches),
        )
    entry = matches[0]
    return entry.text.strip(), None


def _reconstruct_from_docstore(*, project_id: str, source_document_id: Optional[str]) -> str:
    """Reassemble entry text from docstore chunks as an expansion fallback.

    Collects all LTM docstore chunks tagged with ``source_document_id`` and
    joins them in chunk-index order. Returns an empty string when the docstore
    is unavailable or has no matching chunks.

    Args:
        project_id: Project whose LTM docstore is read.
        source_document_id: Document id whose chunks are reassembled.

    Returns:
        The reassembled entry text, or an empty string when the id is missing,
        the docstore is unavailable, or no chunks match.
    """
    if not source_document_id:
        return ""
    docstore_path = os.path.join(get_settings().memory_root, project_id, "faiss", LTM_DOCSTORE_NAME)
    obj = safe_load_json(docstore_path)
    if not isinstance(obj, dict):
        return ""
    chunks: List[Tuple[int, str]] = []
    for entry in obj.values():
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        if metadata.get("source_document_id") != source_document_id:
            continue
        try:
            chunk_index = int(
                metadata.get("chunk_index")
                if metadata.get("chunk_index") is not None
                else metadata.get("chunk_seq")
            )
        except (TypeError, ValueError):
            continue
        text = entry.get("text") if isinstance(entry.get("text"), str) else ""
        chunks.append((chunk_index, text))
    if not chunks:
        return ""
    return "\n".join(text for _idx, text in sorted(chunks, key=lambda item: item[0]) if text)


def _apply_size_guard(
    snippet: AgentMemorySnippet, *, max_chars: int, artifact_expansion: bool
) -> None:
    """Truncate an oversized snippet in place and record truncation metadata.

    No-op when the serialized snippet already fits within ``max_chars``. Sets
    the ``entry_expansion_*`` truncation fields and rewrites ``text`` to fit.

    Args:
        snippet: Snippet mutated in place.
        max_chars: Maximum serialized snippet size in characters.
        artifact_expansion: Whether the text came from a successful artifact
            expansion, which downgrades the status to ``expanded_truncated``.
    """
    serialized_len = _serialized_snippet_chars(snippet)
    if serialized_len <= max_chars:
        return
    original_text = snippet.text or ""
    original_chars = len(original_text)
    if artifact_expansion:
        snippet.entry_expansion_status = "expanded_truncated"
    snippet.entry_expansion_truncated = True
    snippet.entry_expansion_original_chars = original_chars
    snippet.entry_expansion_max_chars = int(max_chars)
    snippet.entry_expansion_truncation_reason = "max_chars_exceeded"

    snippet.text = _truncate_text_to_fit(snippet, original_text=original_text, max_chars=max_chars)
    snippet.entry_expansion_returned_chars = len(snippet.text or "")


def _truncate_text_to_fit(
    snippet: AgentMemorySnippet,
    *,
    original_text: str,
    max_chars: int,
) -> str:
    """Binary-search the longest text prefix whose serialized snippet fits.

    Accounts for the full serialized snippet size (not just text length) since
    other fields contribute to the JSON payload.

    Args:
        snippet: Snippet mutated during the search; its ``text`` and
            ``entry_expansion_returned_chars`` are left set to the best fit.
        original_text: Full untruncated entry text to take a prefix from.
        max_chars: Maximum allowed serialized snippet size in characters.

    Returns:
        The longest truncated text (prefix plus truncation notice) whose
        serialized snippet stays within ``max_chars``.
    """
    low = 0
    high = len(original_text)
    best = _build_truncated_text(original_text, prefix_chars=0)
    while low <= high:
        mid = (low + high) // 2
        candidate = _build_truncated_text(original_text, prefix_chars=mid)
        snippet.text = candidate
        snippet.entry_expansion_returned_chars = len(candidate)
        if _serialized_snippet_chars(snippet) <= max_chars:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _build_truncated_text(original_text: str, *, prefix_chars: int) -> str:
    """Build a truncated entry text: a normalized prefix plus a notice.

    Args:
        original_text: Full entry text to truncate.
        prefix_chars: Number of leading characters to keep before the notice;
            clamped to be non-negative.

    Returns:
        The trimmed prefix followed by :data:`TRUNCATION_NOTICE`.
    """
    normalized = normalize_lf(original_text)
    prefix = normalized[: max(0, int(prefix_chars))].rstrip()
    return f"{prefix}\n\n{TRUNCATION_NOTICE}".strip()


def _serialized_snippet_chars(snippet: AgentMemorySnippet) -> int:
    """Measure a snippet's serialized JSON size used for the size guard.

    Args:
        snippet: Snippet to serialize (null fields excluded).

    Returns:
        The character length of the deterministic JSON serialization.
    """
    payload = snippet.model_dump(exclude_none=True)
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _path_from_source_document_id(source_document_id: Optional[str]) -> Optional[str]:
    """Extract the artifact path portion of a composite source document id.

    Args:
        source_document_id: Id that may carry a ``::memory_id=`` suffix.

    Returns:
        The leading path component, or ``None`` when the id is empty.
    """
    if not source_document_id:
        return None
    return str(source_document_id).split("::memory_id=", 1)[0].strip() or None


def _clean_upload_relative_path(
    value: Optional[str],
    *,
    project_id: str,
    memory_id: Optional[str],
    snippet_number: int,
    field: str,
) -> Optional[str]:
    """Validate and normalize an upload-relative path, rejecting traversal.

    Returns the forward-slash-normalized path, or ``None`` (with a warning) for
    empty, absolute, or ``..``-containing values that could escape the uploads
    directory.

    Args:
        value: Raw upload-relative path to validate.
        project_id: Project id, used only for log context.
        memory_id: Memory entry id, used only for log context.
        snippet_number: Snippet ordinal, used only for log context.
        field: Source field name (e.g. ``artifact_path``) for log context.

    Returns:
        The normalized forward-slash path, or ``None`` when the value is empty
        or fails the traversal safety check.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    if os.path.isabs(normalized) or ".." in normalized.split("/"):
        logger.warning(
            "agent_memory_expand rejected unsafe upload-relative path; project_id=%s snippet_number=%s memory_id=%s field=%s value=%s",
            project_id,
            snippet_number,
            memory_id,
            field,
            raw,
        )
        return None
    return normalized


def _uploads_dir(project_id: str) -> str:
    """Return the absolute uploads directory path for a project.

    Args:
        project_id: Project whose uploads directory is resolved.

    Returns:
        The absolute path to the project's ``uploads`` directory.
    """
    return os.path.abspath(os.path.join(get_settings().memory_root, project_id, "uploads"))


def _is_within(path: str, base: str) -> bool:
    """Report whether a path resolves inside a base directory.

    Args:
        path: Candidate path to test.
        base: Directory that ``path`` must stay within.

    Returns:
        ``True`` when ``path`` is contained in ``base``; ``False`` on mismatch
        or when the paths are not comparable (e.g. different drives).
    """
    try:
        return os.path.commonpath(
            [os.path.abspath(path), os.path.abspath(base)]
        ) == os.path.abspath(base)
    except ValueError:
        return False
