"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Syx markdown memory artifact helpers.

This module owns source-neutral memory IDs, Syx boundary parsing, and the
minimal markdown rendering needed by Daily/Sleep/Dream artifacts.
"""

from dataclasses import dataclass
import hashlib
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

MEMORY_ID_RE = re.compile(r"^mem_\d{8}_\d{6}_[0-9a-f]{4,8}$")
BEGIN_RE = re.compile(r"^<!-- begin syx:memory_id=(mem_\d{8}_\d{6}_[0-9a-f]{4,8}) -->\s*$")
END_RE = re.compile(r"^<!-- end syx:memory_id=(mem_\d{8}_\d{6}_[0-9a-f]{4,8}) -->\s*$")
LOOSE_BEGIN_RE = re.compile(r"^<!-- begin syx:memory_id=(?P<memory_id>[^ ]+) -->\s*$")
LOOSE_END_RE = re.compile(r"^<!-- end syx:memory_id=(?P<memory_id>[^ ]+) -->\s*$")
LEGACY_MEMORY_WRAPPER_RE = re.compile(
    r"^=== (?:BEGIN|END) (?P<kind>DAILY|DREAM) MEMORY:\s*(?P<date>\d{2}/\d{2}/\d{4}) ===\s*\n?",
    re.MULTILINE,
)
BEGIN_MARKER_RE = re.compile(r"(?<!\n\n)(?<!\A)(<!-- begin syx:memory_id=)")
ENTRY_HEADING_RE = re.compile(r"^##\s+.+$", re.MULTILINE)
LEGACY_SEMANTIC_HANDLE_RE = re.compile(r"^#semantic_handle:\s*(?P<value>.+?)\s*$", re.MULTILINE)


@dataclass
class SyxMemoryEntry:
    """A single bounded Syx memory entry with its parsed metadata and span."""

    memory_id: str
    text: str
    metadata: Dict[str, Any]
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int


@dataclass
class SyxParseResult:
    """Outcome of parsing Syx boundaries: entries plus structural/metadata warnings."""

    entries: List[SyxMemoryEntry]
    warnings: List[str]
    occupied_ranges: List[Tuple[int, int]]
    structural_warnings: List[str]
    metadata_warnings: List[str]


def normalize_lf(text: str) -> str:
    """Normalize CRLF/CR line endings to LF.

    Args:
        text: Input text; None is coerced to an empty string.

    Returns:
        The text with all ``\\r\\n`` and ``\\r`` sequences replaced by ``\\n``.
    """
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def local_timestamp_from_iso(created_at_iso_utc: Optional[str]) -> str:
    """Convert an ISO/UTC timestamp into the Syx local ``MM-DD-YYYY_HH:MM:SS`` format.

    Args:
        created_at_iso_utc: ISO-8601 timestamp (``Z``-suffixed UTC or offset-aware
            accepted); None/empty falls back to the current local time.

    Returns:
        The localized timestamp string; on parse failure the original raw value
        is returned unchanged.
    """
    if not created_at_iso_utc:
        return time.strftime("%m-%d-%Y_%H:%M:%S", time.localtime())
    raw = str(created_at_iso_utc).strip()
    try:
        if raw.endswith("Z"):
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%m-%d-%Y_%H:%M:%S")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            return dt.astimezone().strftime("%m-%d-%Y_%H:%M:%S")
        return dt.strftime("%m-%d-%Y_%H:%M:%S")
    except (TypeError, ValueError):
        return raw


def compact_timestamp_for_memory_id(timestamp: str) -> str:
    """Convert supported Syx timestamps into a compact ``YYYYMMDD_HHMMSS`` token.

    Args:
        timestamp: A Syx local/slash timestamp, ISO string, or ``Z``-suffixed UTC.

    Returns:
        The compact timestamp used in memory ids; falls back to the current local
        time when ``timestamp`` cannot be parsed.
    """
    raw = str(timestamp or "").strip()
    for fmt in ("%m-%d-%Y_%H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y%m%d_%H%M%S")
        except ValueError:
            continue
    try:
        if raw.endswith("Z"):
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%Y%m%d_%H%M%S")
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def memory_date_from_local_timestamp(timestamp: Optional[str] = None) -> str:
    """Derive an ``MM-DD-YYYY`` memory date from a Syx timestamp.

    Args:
        timestamp: A Syx local/slash timestamp; None/empty or unparseable input
            falls back to today's local date.

    Returns:
        The memory date in ``MM-DD-YYYY`` format.
    """
    raw = str(timestamp or "").strip()
    for fmt in ("%m-%d-%Y_%H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%m-%d-%Y")
        except ValueError:
            continue
    return time.strftime("%m-%d-%Y", time.localtime())


def slash_date_to_memory_date(date_text: str) -> str:
    """Convert an ``MM/DD/YYYY`` date into the ``MM-DD-YYYY`` memory-date format.

    Args:
        date_text: A slash-delimited date string.

    Returns:
        The dash-delimited memory date; on parse failure, the input with slashes
        naively replaced by dashes.
    """
    try:
        return datetime.strptime(str(date_text).strip(), "%m/%d/%Y").strftime("%m-%d-%Y")
    except ValueError:
        return str(date_text or "").strip().replace("/", "-")


def render_artifact_header(*, artifact_type: str, project_id: str, memory_date: str) -> str:
    """Render the YAML front-matter header block for a Syx memory artifact.

    Args:
        artifact_type: Artifact kind (e.g. ``daily_memory``); also titled for the
            ``# <Title>`` heading.
        project_id: Owning project id recorded in the front matter.
        memory_date: Memory date in ``MM-DD-YYYY`` format.

    Returns:
        The front-matter header plus title heading, terminated with a blank line.
    """
    title = str(artifact_type).replace("_", " ").title()
    return (
        "---\n"
        f"syx_artifact_type: {artifact_type}\n"
        f"project_id: {project_id}\n"
        f"memory_date: {memory_date}\n"
        "format_version: 1\n"
        "---\n\n"
        f"# {title}: {memory_date}\n\n"
    )


def ensure_artifact_header(
    text: str,
    *,
    artifact_type: str,
    project_id: str,
    memory_date: str,
) -> str:
    """Ensure ``text`` begins with a current Syx artifact header.

    Strips legacy memory wrappers and returns the text unchanged when it already
    carries a versioned front-matter header; otherwise prepends a fresh header.

    Args:
        text: Artifact body to normalize and inspect.
        artifact_type: Artifact kind used when a new header must be rendered.
        project_id: Owning project id used when a new header must be rendered.
        memory_date: Memory date used when a new header must be rendered.

    Returns:
        The normalized text guaranteed to start with a versioned front-matter
        header.
    """
    normalized = normalize_lf(text).lstrip()
    normalized = LEGACY_MEMORY_WRAPPER_RE.sub("", normalized).lstrip()
    if normalized.startswith("---\n") and "format_version:" in normalized.split("---", 2)[1]:
        return normalized
    return render_artifact_header(
        artifact_type=artifact_type,
        project_id=project_id,
        memory_date=memory_date,
    ) + normalized


def normalize_legacy_artifact_wrappers(
    text: str,
    *,
    artifact_type: str,
    project_id: str,
    memory_date: Optional[str] = None,
) -> str:
    """Convert legacy ``=== BEGIN/END … MEMORY ===`` wrappers to a current header.

    Resolves the memory date from the explicit argument, then the legacy wrapper,
    then falls back to today's date.

    Args:
        text: Artifact body that may contain legacy wrappers.
        artifact_type: Artifact kind used when rendering the replacement header.
        project_id: Owning project id used when rendering the replacement header.
        memory_date: Explicit memory date; when None it is derived from the legacy
            wrapper date or today's date.

    Returns:
        The text with a current front-matter header in place of any legacy wrapper.
    """
    normalized = normalize_lf(text)
    match = LEGACY_MEMORY_WRAPPER_RE.search(normalized)
    resolved_date = memory_date or (slash_date_to_memory_date(match.group("date")) if match else memory_date_from_local_timestamp())
    return ensure_artifact_header(
        normalized,
        artifact_type=artifact_type,
        project_id=project_id,
        memory_date=resolved_date,
    )


def ensure_blank_line_before_begin_markers(text: str) -> str:
    """Insert a blank line before any begin marker not already preceded by one.

    Args:
        text: Artifact body containing ``<!-- begin syx:memory_id= -->`` markers.

    Returns:
        The normalized text with a blank line separating consecutive entries.
    """
    normalized = normalize_lf(text)
    return BEGIN_MARKER_RE.sub(r"\n\1", normalized)


def _canonical_hash_payload(values: Dict[str, Any]) -> str:
    """Serialize values into a stable, key-sorted string for deterministic hashing.

    Skips None values and joins list values with newlines so that memory-id
    digests are reproducible regardless of input dict ordering.

    Args:
        values: Field name to value mapping forming the hash payload.

    Returns:
        A newline-joined ``key=value`` string with keys sorted and line endings
        normalized.
    """
    parts: List[str] = []
    for key in sorted(values.keys()):
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            rendered = "\n".join(str(v) for v in value)
        else:
            rendered = str(value)
        parts.append(f"{key}={normalize_lf(rendered)}")
    return "\n".join(parts)


def generate_memory_id(
    *,
    project_id: str,
    timestamp: str,
    source: str,
    entry_type: str,
    user_text: Optional[str] = None,
    assistant_text: Optional[str] = None,
    route: Optional[str] = None,
    semantic_handle: Optional[str] = None,
    dream_output_type: Optional[str] = None,
    accepted_item_id: Optional[str] = None,
    origin_memory_ids: Optional[Iterable[str]] = None,
    dream_content: Optional[str] = None,
) -> str:
    """Generate a deterministic ``mem_<timestamp>_<digest>`` memory id.

    The digest is derived from a canonical payload that varies by entry type:
    dream outputs hash dream-specific fields while other entries hash the
    user/assistant text. Identical inputs always yield the same id.

    Args:
        project_id: Owning project id, always part of the payload.
        timestamp: Source timestamp; compacted into the id prefix and hashed.
        source: Origin of the entry (e.g. ``chat``).
        entry_type: Entry kind; ``dream_output`` selects the dream payload shape.
        user_text: User message text hashed for non-dream entries.
        assistant_text: Assistant message text hashed for non-dream entries.
        route: Optional route name included when present.
        semantic_handle: Optional semantic handle included when present.
        dream_output_type: Dream subtype hashed for dream outputs.
        accepted_item_id: Accepted item id hashed for dream outputs.
        origin_memory_ids: Source memory ids hashed for dream outputs (empties
            dropped).
        dream_content: Dream body text hashed for dream outputs.

    Returns:
        A deterministic id of the form ``mem_<YYYYMMDD_HHMMSS>_<8-hex-digest>``.
    """
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "timestamp": timestamp,
        "source": source,
        "entry_type": entry_type,
    }
    if route:
        payload["route"] = route
    if semantic_handle:
        payload["semantic_handle"] = semantic_handle
    if entry_type == "dream_output":
        if dream_output_type:
            payload["dream_output_type"] = dream_output_type
        if accepted_item_id:
            payload["accepted_item_id"] = accepted_item_id
        ids = [str(v) for v in (origin_memory_ids or []) if str(v or "").strip()]
        if ids:
            payload["origin_memory_ids"] = ids
        if dream_content:
            payload["dream_content"] = dream_content
    else:
        payload["user_text"] = user_text or ""
        payload["assistant_text"] = assistant_text or ""
    digest = hashlib.sha256(_canonical_hash_payload(payload).encode("utf-8")).hexdigest()[:8]
    return f"mem_{compact_timestamp_for_memory_id(timestamp)}_{digest}"


def split_pair_text(pair_text: str) -> Tuple[str, str]:
    """Split combined ``User:/Assistant:`` pair text into (user, assistant) parts.

    Args:
        pair_text: Combined pair text; line endings are normalized first.

    Returns:
        A ``(user_text, assistant_text)`` tuple. When no ``\\nAssistant:``
        delimiter is present, the user part is empty and the whole text is treated
        as the assistant part.
    """
    text = normalize_lf(pair_text)
    if "\nAssistant:" in text:
        user_part, assistant_part = text.split("\nAssistant:", 1)
        return user_part.replace("User:", "", 1).strip(), assistant_part.strip()
    return "", text.strip()


def topics_to_list(value: Any) -> List[str]:
    """Coerce a topics value into a clean list of strings.

    Accepts an existing list or a scalar, splitting scalars on common tagger
    separators (``,`` and ``;``) and dropping empties.

    Args:
        value: Topics as a list, scalar string, or None.

    Returns:
        A list of trimmed, non-empty topic strings; empty for None/blank input.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v or "").strip()]
    raw = str(value or "").strip()
    if not raw:
        return []
    # Preserve simple scalar topics, but split common tagger separators.
    return [part.strip() for part in re.split(r"[,;]", raw) if part.strip()]


def snake_case_value(value: Any) -> str:
    """Normalize an arbitrary value into a lowercase snake_case token.

    Args:
        value: Any value; stringified and stripped of non-alphanumerics.

    Returns:
        The snake_case token, or an empty string when the input is empty/None.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower()


def entry_type_label(entry_type: Any) -> str:
    """Render an entry_type as a human-readable Title Case label.

    Args:
        entry_type: Entry type token; empty/None defaults to ``memory_entry``.

    Returns:
        The label with underscores replaced by spaces and title-cased.
    """
    raw = str(entry_type or "memory_entry").strip()
    if not raw:
        raw = "memory_entry"
    return raw.replace("_", " ").title()


def entry_heading(metadata: Dict[str, Any]) -> str:
    """Build the ``## <label>[: <semantic_handle>]`` heading for an entry.

    Args:
        metadata: Entry metadata read for ``entry_type`` and ``semantic_handle``.

    Returns:
        A markdown heading, suffixing the semantic handle when one is present.
    """
    label = entry_type_label(metadata.get("entry_type"))
    semantic_handle = str(metadata.get("semantic_handle") or "").strip()
    if semantic_handle:
        return f"## {label}: {semantic_handle}"
    return f"## {label}"


def render_yaml_block(metadata: Dict[str, Any]) -> str:
    """Render entry metadata as the fenced ``### Syx Metadata`` YAML block.

    Skips None values and renders booleans lowercased and lists as YAML sequences.

    Args:
        metadata: Entry metadata to serialize; insertion order is preserved.

    Returns:
        The ``### Syx Metadata`` section including the fenced YAML block.
    """
    lines: List[str] = ["### Syx Metadata", "", "```yaml"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {str(item)}")
        else:
            rendered = str(value).replace("\n", " ").strip()
            lines.append(f"{key}: {rendered}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def render_memory_entry(
    *,
    memory_id: str,
    metadata: Dict[str, Any],
    user_text: Optional[str] = None,
    assistant_text: Optional[str] = None,
    body_text: Optional[str] = None,
) -> str:
    """Render a complete bounded Syx memory entry block.

    Wraps the heading, metadata YAML, and content in begin/end markers. When
    ``body_text`` is given it is used as the body; otherwise the user and
    assistant messages are rendered as separate sections.

    Args:
        memory_id: Stable id emitted in the begin/end boundary markers.
        metadata: Entry metadata rendered as the YAML block and heading.
        user_text: User message rendered when ``body_text`` is not supplied.
        assistant_text: Assistant message rendered when ``body_text`` is not
            supplied.
        body_text: Pre-rendered body; when provided it replaces the separate
            user/assistant sections.

    Returns:
        The full entry block (markers, heading, metadata, content) terminated
        with trailing newlines.
    """
    parts = [
        f"<!-- begin syx:memory_id={memory_id} -->",
        entry_heading(metadata),
        "",
        render_yaml_block(metadata).rstrip(),
    ]
    if body_text is not None:
        parts.extend(["", normalize_lf(body_text).strip()])
    else:
        parts.extend(
            [
                "",
                "### User Message",
                normalize_lf(user_text or "").strip(),
                "",
                "### Assistant Message",
                normalize_lf(assistant_text or "").strip(),
            ]
        )
    parts.extend(["", f"<!-- end syx:memory_id={memory_id} -->", "", ""])
    return "\n".join(parts)


def _parse_scalar(value: str) -> Any:
    """Coerce a YAML scalar string into a bool or trimmed string.

    Args:
        value: Raw scalar text from a metadata line.

    Returns:
        ``True``/``False`` for case-insensitive boolean literals, otherwise the
        stripped string.
    """
    raw = value.strip()
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return raw


def parse_yaml_metadata_with_warnings(entry_text: str) -> Tuple[Dict[str, Any], List[str]]:
    """Parse the ``### Syx Metadata`` YAML block from an entry body.

    Supports scalar values and simple ``- item`` lists under a bare key.

    Args:
        entry_text: Entry body text containing the metadata block.

    Returns:
        A tuple of (parsed metadata, warnings). Warnings flag malformed fences
        and unparseable lines; an empty dict is returned when no block is found.
    """
    lines = normalize_lf(entry_text).splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "### Syx Metadata":
            continue
        if idx + 2 >= len(lines) or lines[idx + 1].strip() or lines[idx + 2].strip() != "```yaml":
            return {}, [f"invalid Syx metadata fence after line {idx + 1}"]
        out: Dict[str, Any] = {}
        warnings: List[str] = []
        current_list_key: Optional[str] = None
        for rel_idx, raw in enumerate(lines[idx + 3 :], start=idx + 4):
            stripped = raw.strip()
            if stripped == "```":
                return out, warnings
            if not stripped:
                continue
            if stripped.startswith("- ") and current_list_key:
                out.setdefault(current_list_key, []).append(stripped[2:].strip())
                continue
            if ":" not in stripped:
                warnings.append(f"invalid Syx metadata line {rel_idx}: missing ':'")
                current_list_key = None
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            if not key:
                warnings.append(f"invalid Syx metadata line {rel_idx}: empty key")
                current_list_key = None
                continue
            if value.strip():
                out[key] = _parse_scalar(value)
                current_list_key = None
            else:
                out[key] = []
                current_list_key = key
        return out, [*warnings, f"invalid Syx metadata fence after line {idx + 1}: missing closing fence"]
    return {}, []


def parse_yaml_metadata(entry_text: str) -> Dict[str, Any]:
    """Parse the entry's Syx metadata block, discarding any warnings.

    Args:
        entry_text: Entry body text containing the metadata block.

    Returns:
        The parsed metadata dict (empty when no block is found).
    """
    metadata, _warnings = parse_yaml_metadata_with_warnings(entry_text)
    return metadata


def legacy_semantic_handle(entry_text: str) -> Optional[str]:
    """Extract a legacy ``#semantic_handle:`` value from entry text, if present.

    Args:
        entry_text: Entry body text to scan for the legacy directive.

    Returns:
        The trimmed handle value, or None when absent or empty.
    """
    match = LEGACY_SEMANTIC_HANDLE_RE.search(normalize_lf(entry_text))
    if not match:
        return None
    value = match.group("value").strip()
    return value or None


def ensure_entry_headings(text: str) -> str:
    """Insert a ``##`` heading into any bounded entry that lacks one.

    Reparses the text and, for each entry whose first lines have no heading,
    synthesizes one from its metadata (recovering a legacy semantic handle when
    available). Text outside bounded entries is preserved verbatim.

    Args:
        text: Artifact body containing zero or more bounded entries.

    Returns:
        The text with synthesized headings inserted where missing; unchanged when
        no bounded entries are found.
    """
    normalized = normalize_lf(text)
    parsed = parse_syx_entries(normalized)
    if not parsed.entries:
        return normalized
    pieces: List[str] = []
    cursor = 0
    for entry in parsed.entries:
        pieces.append(normalized[cursor:entry.start_offset])
        block = normalized[entry.start_offset:entry.end_offset]
        block_lines = block.splitlines(keepends=True)
        if len(block_lines) > 1:
            probe = "".join(block_lines[1:5])
            if not ENTRY_HEADING_RE.search(probe):
                metadata = dict(entry.metadata)
                if not metadata.get("semantic_handle"):
                    legacy_handle = legacy_semantic_handle(entry.text)
                    if legacy_handle:
                        metadata["semantic_handle"] = legacy_handle
                heading = entry_heading(metadata)
                block = block_lines[0] + f"\n{heading}\n\n" + "".join(block_lines[1:])
        pieces.append(block)
        cursor = entry.end_offset
    pieces.append(normalized[cursor:])
    return "".join(pieces)


def parse_syx_entries(text: str, *, artifact_path: Optional[str] = None) -> SyxParseResult:
    """Parse bounded Syx memory entries from artifact text.

    Walks begin/end markers, parsing each well-formed entry's metadata and span
    and collecting structural warnings (invalid, mismatched, duplicate, or
    unterminated markers). When provided, ``artifact_path`` is recorded on each
    entry's metadata as a default ``artifact_path``.

    Args:
        text: Artifact body to scan for bounded Syx entries.
        artifact_path: Optional source path stored as a default on each entry's
            metadata for downstream attribution.

    Returns:
        A SyxParseResult with parsed entries, occupied ranges, and warnings.
    """
    normalized = normalize_lf(text)
    lines = normalized.splitlines(keepends=True)
    entries: List[SyxMemoryEntry] = []
    structural_warnings: List[str] = []
    metadata_warnings: List[str] = []
    occupied: List[Tuple[int, int]] = []
    seen: set[str] = set()
    offset = 0
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        begin = BEGIN_RE.match(line.rstrip("\n"))
        if not begin:
            if LOOSE_BEGIN_RE.match(line.rstrip("\n")):
                structural_warnings.append(f"invalid begin marker at line {idx + 1}")
            if END_RE.match(line.rstrip("\n")):
                structural_warnings.append(f"end without begin at line {idx + 1}")
            elif LOOSE_END_RE.match(line.rstrip("\n")):
                structural_warnings.append(f"invalid end marker at line {idx + 1}")
            offset += len(line)
            idx += 1
            continue
        memory_id = begin.group(1)
        start_idx = idx
        start_offset = offset
        idx += 1
        offset += len(line)
        body_start_offset = offset
        found = False
        while idx < len(lines):
            end = END_RE.match(lines[idx].rstrip("\n"))
            if end:
                end_offset = offset + len(lines[idx])
                if end.group(1) != memory_id:
                    structural_warnings.append(f"mismatched end marker for memory_id={memory_id} at line {idx + 1}")
                    found = True
                    break
                body_text = normalized[body_start_offset:offset]
                if memory_id in seen:
                    structural_warnings.append(f"duplicate memory_id={memory_id} at line {start_idx + 1}")
                    occupied.append((start_offset, end_offset))
                    found = True
                    break
                seen.add(memory_id)
                metadata, entry_metadata_warnings = parse_yaml_metadata_with_warnings(body_text)
                metadata_warnings.extend(
                    f"memory_id={memory_id}: {warning}" for warning in entry_metadata_warnings
                )
                metadata.setdefault("memory_id", memory_id)
                if artifact_path:
                    metadata.setdefault("artifact_path", artifact_path)
                entries.append(
                    SyxMemoryEntry(
                        memory_id=memory_id,
                        text=body_text,
                        metadata=metadata,
                        start_line=start_idx + 1,
                        end_line=idx + 1,
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
                )
                occupied.append((start_offset, end_offset))
                found = True
                break
            offset += len(lines[idx])
            idx += 1
        if not found:
            structural_warnings.append(f"begin without end for memory_id={memory_id} at line {start_idx + 1}")
            continue
        if idx < len(lines):
            offset += len(lines[idx])
            idx += 1
    warnings = [*structural_warnings, *metadata_warnings]
    return SyxParseResult(
        entries=entries,
        warnings=warnings,
        occupied_ranges=occupied,
        structural_warnings=structural_warnings,
        metadata_warnings=metadata_warnings,
    )


def validate_syx_boundaries(text: str) -> Tuple[bool, List[str]]:
    """Validate Syx boundary markers in ``text``.

    Args:
        text: Artifact body to validate.

    Returns:
        A tuple of (is_valid, warnings) where ``is_valid`` is True only when
        parsing produced no warnings.
    """
    result = parse_syx_entries(text)
    return len(result.warnings) == 0, result.warnings


def replace_current_scope_for_ltm(text: str) -> str:
    """Rewrite bounded entries' ``current_scope`` to ``ltm`` for LTM artifacts.

    Args:
        text: Artifact body whose bounded entries should be rescoped.

    Returns:
        The text with each entry's ``current_scope`` line set to ``ltm``;
        unchanged when no bounded entries are present. Content outside entries is
        preserved verbatim.
    """
    normalized = normalize_lf(text)
    result = parse_syx_entries(normalized)
    if not result.entries:
        return normalized
    pieces: List[str] = []
    cursor = 0
    for entry in result.entries:
        pieces.append(normalized[cursor:entry.start_offset])
        block = normalized[entry.start_offset:entry.end_offset]
        block = re.sub(r"(?m)^current_scope:\s*\S+\s*$", "current_scope: ltm", block)
        pieces.append(block)
        cursor = entry.end_offset
    pieces.append(normalized[cursor:])
    return "".join(pieces)


def unbounded_regions(text: str, occupied_ranges: List[Tuple[int, int]]) -> List[str]:
    """Return the non-empty text regions that fall outside the occupied ranges.

    Used to recover content that is not enclosed by Syx boundary markers. Ranges
    are sorted and merged; only regions with non-whitespace content are returned.

    Args:
        text: Artifact body to scan; line endings are normalized first.
        occupied_ranges: ``(start_offset, end_offset)`` spans already claimed by
            bounded entries.

    Returns:
        The list of unclaimed, non-whitespace text regions in document order.
    """
    normalized = normalize_lf(text)
    if not occupied_ranges:
        return [normalized] if normalized.strip() else []
    regions: List[str] = []
    cursor = 0
    for start, end in sorted(occupied_ranges):
        if start > cursor:
            region = normalized[cursor:start]
            if region.strip():
                regions.append(region)
        cursor = max(cursor, end)
    if cursor < len(normalized):
        region = normalized[cursor:]
        if region.strip():
            regions.append(region)
    return regions
