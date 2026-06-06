"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""A.5 full-entry expansion for agent memory search snippets."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    """Expand bounded snippets to full Syx entries while preserving A.4 ordering."""
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
        _apply_size_guard(snippet, max_chars=max_chars, artifact_expansion=result.status == "expanded")
        out.append(snippet)
    return out


def _expand_one(*, project_id: str, snippet: AgentMemorySnippet) -> _ExpansionResult:
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
        expanded, error = _extract_from_artifact(project_id, artifact_path, str(snippet.memory_id), snippet.snippet_number)
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

    reconstructed = _reconstruct_from_docstore(project_id=project_id, source_document_id=snippet.source_document_id)
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
            chunk_index = int(metadata.get("chunk_index") if metadata.get("chunk_index") is not None else metadata.get("chunk_seq"))
        except (TypeError, ValueError):
            continue
        text = entry.get("text") if isinstance(entry.get("text"), str) else ""
        chunks.append((chunk_index, text))
    if not chunks:
        return ""
    return "\n".join(text for _idx, text in sorted(chunks, key=lambda item: item[0]) if text)


def _apply_size_guard(snippet: AgentMemorySnippet, *, max_chars: int, artifact_expansion: bool) -> None:
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
    normalized = normalize_lf(original_text)
    prefix = normalized[: max(0, int(prefix_chars))].rstrip()
    return f"{prefix}\n\n{TRUNCATION_NOTICE}".strip()


def _serialized_snippet_chars(snippet: AgentMemorySnippet) -> int:
    payload = snippet.model_dump(exclude_none=True)
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _path_from_source_document_id(source_document_id: Optional[str]) -> Optional[str]:
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
    return os.path.abspath(os.path.join(get_settings().memory_root, project_id, "uploads"))


def _is_within(path: str, base: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except ValueError:
        return False
