"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""Best-effort parser for prompt-shaped retrieval context."""

import re
from typing import Any, Dict, List, Optional

from .models import AgentMemorySnippet


class SnippetParseError(ValueError):
    """Raised when non-empty retrieval context cannot be parsed into snippets."""

    def __init__(self, message: str, *, raw_context: str = "") -> None:
        super().__init__(message)
        self.raw_context = raw_context


_HEADER_RE = re.compile(r"^Snippet\s+(\d+)\s+\((?P<meta>.*?)\)\s*$")
_YAML_RE = re.compile(r"```yaml\s*\n(?P<body>.*?)\n```", re.DOTALL)
_INT_RE = re.compile(r"^-?\d+$")


def parse_prompt_context_to_snippets(context_text: str) -> List[AgentMemorySnippet]:
    """Parse prompt-shaped retrieval context into structured snippets.

    Args:
        context_text: Raw prompt context produced by retrieval.

    Returns:
        Parsed snippets in document order; an empty list when the context is
        empty or contains no snippet blocks.

    Raises:
        SnippetParseError: If a detected snippet block cannot be parsed.
    """
    text = str(context_text or "").strip()
    if not text:
        return []
    body = _strip_context_prefix(text)
    parts = _split_snippet_parts(body)
    if not parts:
        return []

    snippets: List[AgentMemorySnippet] = []
    for part in parts:
        snippet = _parse_part(part)
        if snippet is None:
            raise SnippetParseError("retrieval context contained an unparseable snippet block")
        snippets.append(snippet)
    return snippets


def _split_snippet_parts(body: str) -> List[str]:
    """Split context body into per-snippet text blocks.

    Only header lines that follow a ``---`` delimiter (or start the body) are
    treated as snippet boundaries, so ``Snippet N`` text appearing inside a
    snippet's own content is not mistaken for a new block.

    Args:
        body: Context body with the ``Context:`` prefix already stripped.

    Returns:
        Per-snippet text blocks in document order; an empty list when no
        snippet boundaries are found.
    """
    lines = str(body or "").splitlines()
    starts = [
        idx
        for idx, line in enumerate(lines)
        if _HEADER_RE.match(line.strip()) and _is_context_delimited_snippet_start(lines, idx)
    ]
    if not starts:
        return []
    parts: List[str] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        part = "\n".join(lines[start:end]).strip()
        if part:
            parts.append(part)
    return parts


def _is_context_delimited_snippet_start(lines: List[str], idx: int) -> bool:
    """Report whether a header line marks a real snippet boundary.

    A header qualifies when it is the first content line or the previous
    non-blank line is the ``---`` block delimiter.

    Args:
        lines: All context body lines.
        idx: Index of the candidate header line within ``lines``.

    Returns:
        ``True`` when the header at ``idx`` begins a new snippet block.
    """
    if idx <= 0:
        return True
    prev_idx = idx - 1
    while prev_idx >= 0 and not lines[prev_idx].strip():
        prev_idx -= 1
    if prev_idx < 0:
        return True
    return lines[prev_idx].strip() == "---"


def render_prompt_text_from_snippets(snippets: List[AgentMemorySnippet]) -> str:
    """Render snippets back into the prompt-shaped context format.

    Inverse of :func:`parse_prompt_context_to_snippets`; returns an empty
    string when there are no snippets.

    Args:
        snippets: Snippets to serialize back into prompt-shaped context.

    Returns:
        The rendered context string, or an empty string when ``snippets`` is
        empty.
    """
    pieces: List[str] = []
    for snippet in snippets or []:
        header = _render_header(snippet)
        pieces.append(header + "\n" + (snippet.text or ""))
    return ("Context:\n---\n" + "\n\n---\n".join(pieces)) if pieces else ""


def _strip_context_prefix(text: str) -> str:
    """Strip the leading ``Context:`` block delimiter from retrieval text.

    Args:
        text: Raw, already-trimmed context string.

    Returns:
        The text with a leading ``Context:\\n---\\n`` (LF or CRLF) prefix
        removed; the input unchanged when no such prefix is present.
    """
    if text.startswith("Context:\n---\n"):
        return text[len("Context:\n---\n") :].strip()
    if text.startswith("Context:\r\n---\r\n"):
        return text[len("Context:\r\n---\r\n") :].strip()
    return text


def _parse_part(part: str) -> Optional[AgentMemorySnippet]:
    """Parse one snippet block into an ``AgentMemorySnippet``.

    Merges metadata from the header line and the first embedded YAML block,
    preferring YAML values. Presence of ``memory_id`` marks the snippet as a
    ``bounded_entry``; otherwise it is an ``unbounded_chunk_group``.

    Args:
        part: Text of a single snippet block, header line first.

    Returns:
        The parsed snippet, or ``None`` when the block has no valid header.
    """
    lines = part.splitlines()
    if not lines:
        return None
    match = _HEADER_RE.match(lines[0].strip())
    if not match:
        return None

    header_meta = _parse_header_meta(match.group("meta"))
    body = "\n".join(lines[1:]).strip()
    yaml_meta = _parse_first_yaml_block(body)
    snippet_number = int(match.group(1))
    source = _as_str(header_meta.get("source"))
    score = _as_float(header_meta.get("score"))
    cos = _as_float(header_meta.get("cos"))
    chunk_start, chunk_end, chunk_range = _parse_chunk_index(_as_str(header_meta.get("chunk_index")))

    memory_id = _as_str(yaml_meta.get("memory_id")) or _as_str(header_meta.get("memory_id"))
    artifact_path = _as_str(yaml_meta.get("artifact_path")) or _as_str(header_meta.get("artifact_path"))
    source_document_id = _source_document_id(
        explicit=_as_str(yaml_meta.get("source_document_id")) or _as_str(header_meta.get("source_document_id")),
        artifact_path=artifact_path,
        memory_id=memory_id,
    )
    result_mode = "bounded_entry" if memory_id else "unbounded_chunk_group"

    return AgentMemorySnippet(
        snippet_number=snippet_number,
        source=source,
        cos=cos,
        score=score,
        file=_none_if_literal_none(_as_str(header_meta.get("file"))),
        page=_parse_page(header_meta.get("page")),
        source_document_id=source_document_id,
        chunk_index_start=chunk_start,
        chunk_index_end=chunk_end,
        chunk_index_range=chunk_range,
        memory_id=memory_id,
        entry_type=_as_str(yaml_meta.get("entry_type")) or _as_str(header_meta.get("entry_type")),
        source_agent=_as_str(yaml_meta.get("source_agent")) or _as_str(header_meta.get("source_agent")),
        source_scope=_as_str(yaml_meta.get("source_scope")) or _as_str(header_meta.get("source_scope")),
        current_scope=_as_str(yaml_meta.get("current_scope")) or _as_str(header_meta.get("current_scope")),
        semantic_handle=_as_str(yaml_meta.get("semantic_handle")) or _as_str(header_meta.get("semantic_handle")),
        topics=_topics(yaml_meta.get("topics")),
        artifact_path=artifact_path,
        result_mode=result_mode,
        text=body,
    )


def _parse_header_meta(raw: str) -> Dict[str, str]:
    """Parse a header's comma-separated ``key=value`` metadata segment.

    Args:
        raw: The metadata text captured from inside the header parentheses.

    Returns:
        A mapping of trimmed keys to trimmed values; pieces without ``=`` are
        ignored.
    """
    out: Dict[str, str] = {}
    for piece in str(raw or "").split(","):
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _parse_first_yaml_block(text: str) -> Dict[str, Any]:
    """Parse the first fenced ```yaml`` block found in snippet body text.

    Args:
        text: Snippet body that may contain a fenced YAML metadata block.

    Returns:
        The parsed key/value mapping, or an empty dict when no YAML block is
        present.
    """
    match = _YAML_RE.search(text or "")
    if not match:
        return {}
    return _parse_simple_yaml(match.group("body"))


def _parse_simple_yaml(raw: str) -> Dict[str, Any]:
    """Parse a minimal YAML subset (scalars and simple ``- `` lists).

    Intentionally avoids a full YAML dependency: only flat ``key: value`` pairs
    and indented block lists are supported, with scalar coercion via
    :func:`_clean_scalar`.

    Args:
        raw: The YAML block body (without the fence markers).

    Returns:
        A mapping of keys to coerced scalar values or lists; comments and blank
        lines are skipped.
    """
    out: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            out.setdefault(current_list_key, []).append(_clean_scalar(stripped[2:]))
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            out[key] = []
            current_list_key = key
        else:
            out[key] = _clean_scalar(value)
    return out


def _clean_scalar(value: str) -> Any:
    """Coerce a raw YAML scalar token into a typed Python value.

    Strips matching quotes and recognizes ``null``/``true``/``false``, inline
    ``[...]`` lists, and integers; everything else is returned as a string.

    Args:
        value: Raw scalar text to coerce.

    Returns:
        The coerced value: ``None``, ``bool``, ``int``, ``list``, or ``str``.
    """
    v = value.strip()
    if not v:
        return ""
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    lower = v.lower()
    if lower == "null":
        return None
    if lower == "true":
        return True
    if lower == "false":
        return False
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_clean_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    if _INT_RE.match(v):
        try:
            return int(v)
        except ValueError:
            return v
    return v


def _parse_chunk_index(value: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse a chunk-index token into (start, end, canonical range string).

    Accepts a single index (``5``) or a ``start..end`` range; returns all-None
    when the value is missing or unparseable.

    Args:
        value: Raw ``chunk_index`` token from header metadata.

    Returns:
        A ``(start, end, range_string)`` tuple. For a single index, start and
        end are equal; all three are ``None`` when the value cannot be parsed.
    """
    if not value:
        return None, None, None
    v = value.strip()
    if ".." in v:
        start_raw, end_raw = v.split("..", 1)
        start = _as_int(start_raw)
        end = _as_int(end_raw)
        return start, end, v if start is not None and end is not None else None
    single = _as_int(v)
    if single is None:
        return None, None, None
    return single, single, str(single)


def _source_document_id(
    *,
    explicit: Optional[str],
    artifact_path: Optional[str],
    memory_id: Optional[str],
) -> Optional[str]:
    """Resolve a source document id, synthesizing one when only parts exist.

    Prefers an explicit id; otherwise composes ``{artifact_path}::memory_id=...``
    when both parts are present, else returns ``None``.

    Args:
        explicit: An already-resolved source document id, if available.
        artifact_path: Uploaded artifact path used to synthesize an id.
        memory_id: Memory entry id used to synthesize an id.

    Returns:
        The resolved or synthesized source document id, or ``None`` when none
        can be formed.
    """
    if explicit:
        return explicit
    if artifact_path and memory_id:
        return f"{artifact_path}::memory_id={memory_id}"
    return None


def _topics(value: Any) -> Optional[List[str]]:
    """Normalize a topics value into a clean list of non-empty strings.

    Accepts a list or a single string (comma-splitting when commas are
    present).

    Args:
        value: Raw topics value from header or YAML metadata.

    Returns:
        A list of trimmed topic strings, or ``None`` when no topics remain.
    """
    if isinstance(value, list):
        vals = [str(v).strip() for v in value if str(v or "").strip()]
        return vals or None
    if isinstance(value, str) and value.strip():
        if "," in value:
            vals = [v.strip() for v in value.split(",") if v.strip()]
            return vals or None
        return [value.strip()]
    return None


def _parse_page(value: Any) -> Any:
    """Normalize a page value, coercing numeric strings and literal ``none``.

    Args:
        value: Raw page value from header metadata.

    Returns:
        ``None`` for missing/``none`` values, an ``int`` for numeric strings,
        or the original value otherwise.
    """
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if v.lower() == "none" or v == "":
            return None
        parsed = _as_int(v)
        return parsed if parsed is not None else v
    return value


def _none_if_literal_none(value: Optional[str]) -> Optional[str]:
    """Treat the literal string ``"none"`` as an absent value.

    Args:
        value: Candidate string that may carry the literal token ``none``.

    Returns:
        ``None`` when the value is ``None`` or case-insensitively ``"none"``;
        otherwise the original value.
    """
    if value is None:
        return None
    if value.strip().lower() == "none":
        return None
    return value


def _as_str(value: Any) -> Optional[str]:
    """Coerce a value to a trimmed string, mapping blanks to ``None``.

    Args:
        value: Value to stringify.

    Returns:
        The stripped string, or ``None`` when the input is ``None`` or blank.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> Optional[float]:
    """Coerce a value to ``float``, returning ``None`` on failure.

    Args:
        value: Value to convert.

    Returns:
        The parsed float, or ``None`` when the value is ``None`` or not
        numeric.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    """Coerce a value to ``int``, returning ``None`` on failure.

    Args:
        value: Value to convert.

    Returns:
        The parsed integer, or ``None`` when the value is ``None`` or not an
        integer.
    """
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _render_header(snippet: AgentMemorySnippet) -> str:
    """Render a snippet's metadata into a prompt-shaped header line.

    Reconstructs the ``chunk_index`` token from the snippet's range or
    start/end fields, and omits ``file``/``page`` for ``daily`` snippets.

    Args:
        snippet: Snippet whose metadata is rendered.

    Returns:
        A ``Snippet N (...)`` header line matching the parser's expected
        format.
    """
    chunk = snippet.chunk_index_range
    if not chunk and snippet.chunk_index_start is not None and snippet.chunk_index_end is not None:
        if snippet.chunk_index_start == snippet.chunk_index_end:
            chunk = str(snippet.chunk_index_start)
        else:
            chunk = f"{snippet.chunk_index_start}..{snippet.chunk_index_end}"
    bits = [
        f"source={snippet.source}",
        f"cos={snippet.cos:.4f}" if snippet.cos is not None else "cos=None",
        f"score={snippet.score:.4f}" if snippet.score is not None else "score=None",
    ]
    if snippet.source == "daily":
        bits.append("route=None")
    else:
        bits.append(f"file={snippet.file}")
        bits.append(f"page={snippet.page}")
    bits.append(f"chunk_index={chunk}")
    return f"Snippet {snippet.snippet_number} ({', '.join(bits)})"
