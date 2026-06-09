"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Tests for the pure helper functions in app.rag.syx_memory_artifact.

Complements test_syx_memory_artifact.py by exercising timestamp/date coercion,
deterministic memory-id payloads, scalar/topic normalization, YAML metadata
parsing (including malformed fences), structural boundary warnings, and
unbounded-region recovery.
"""

import re

from app.rag.syx_memory_artifact import (
    _canonical_hash_payload,
    _parse_scalar,
    compact_timestamp_for_memory_id,
    ensure_artifact_header,
    ensure_entry_headings,
    entry_type_label,
    generate_memory_id,
    legacy_semantic_handle,
    local_timestamp_from_iso,
    memory_date_from_local_timestamp,
    normalize_legacy_artifact_wrappers,
    parse_syx_entries,
    parse_yaml_metadata,
    parse_yaml_metadata_with_warnings,
    render_artifact_header,
    render_memory_entry,
    render_yaml_block,
    replace_current_scope_for_ltm,
    slash_date_to_memory_date,
    snake_case_value,
    split_pair_text,
    topics_to_list,
    unbounded_regions,
)

_LOCAL_TS_RE = re.compile(r"^\d{2}-\d{2}-\d{4}_\d{2}:\d{2}:\d{2}$")
_COMPACT_RE = re.compile(r"^\d{8}_\d{6}$")


# --- local_timestamp_from_iso ---------------------------------------------


def test_local_timestamp_empty_uses_now():
    assert _LOCAL_TS_RE.match(local_timestamp_from_iso(None))
    assert _LOCAL_TS_RE.match(local_timestamp_from_iso(""))


def test_local_timestamp_offset_aware_converts_to_local():
    out = local_timestamp_from_iso("2026-05-07T21:42:00+00:00")
    assert _LOCAL_TS_RE.match(out)


def test_local_timestamp_naive_iso_formatted_directly():
    assert local_timestamp_from_iso("2026-05-07T21:42:00") == "05-07-2026_21:42:00"


def test_local_timestamp_z_suffixed_utc():
    assert local_timestamp_from_iso("2026-05-07T21:42:00Z") == "05-07-2026_21:42:00"


def test_local_timestamp_invalid_returns_raw():
    assert local_timestamp_from_iso("not-a-timestamp") == "not-a-timestamp"


# --- memory_date_from_local_timestamp -------------------------------------


def test_memory_date_from_local_timestamp_variants():
    assert memory_date_from_local_timestamp("05-07-2026_21:42:00") == "05-07-2026"
    assert memory_date_from_local_timestamp("05/07/2026 21:42:00") == "05-07-2026"
    assert memory_date_from_local_timestamp("05/07/2026") == "05-07-2026"
    # Unparseable -> today's local date (MM-DD-YYYY shape).
    assert re.match(r"^\d{2}-\d{2}-\d{4}$", memory_date_from_local_timestamp("nope"))


# --- compact_timestamp_for_memory_id --------------------------------------


def test_compact_timestamp_local_format():
    assert compact_timestamp_for_memory_id("05-07-2026_21:42:00") == "20260507_214200"


def test_compact_timestamp_slash_format():
    assert compact_timestamp_for_memory_id("05/07/2026 21:42:00") == "20260507_214200"


def test_compact_timestamp_z_suffixed_utc():
    assert compact_timestamp_for_memory_id("2026-05-07T21:42:00Z") == "20260507_214200"


def test_compact_timestamp_isoformat():
    assert compact_timestamp_for_memory_id("2026-05-07T21:42:00") == "20260507_214200"


def test_compact_timestamp_invalid_falls_back_to_now():
    assert _COMPACT_RE.match(compact_timestamp_for_memory_id("garbage"))


# --- slash_date_to_memory_date --------------------------------------------


def test_slash_date_to_memory_date_happy():
    assert slash_date_to_memory_date("05/07/2026") == "05-07-2026"


def test_slash_date_to_memory_date_invalid_naive_replace():
    assert slash_date_to_memory_date("13/40/abcd") == "13-40-abcd"


# --- _canonical_hash_payload ----------------------------------------------


def test_canonical_hash_payload_skips_none_and_joins_lists():
    out = _canonical_hash_payload({"b": None, "a": "x", "c": ["1", "2"]})
    # None dropped, keys sorted, list newline-joined.
    assert out == "a=x\nc=1\n2"


# --- generate_memory_id ---------------------------------------------------


def test_generate_memory_id_is_deterministic_and_shaped():
    kwargs = dict(
        project_id="p",
        timestamp="05-07-2026_21:42:00",
        source="chat",
        entry_type="chat_pair",
        user_text="hi",
        assistant_text="hello",
    )
    a = generate_memory_id(**kwargs)
    b = generate_memory_id(**kwargs)
    assert a == b
    assert re.match(r"^mem_\d{8}_\d{6}_[0-9a-f]{8}$", a)


def test_generate_memory_id_includes_route_and_semantic_handle():
    base = dict(
        project_id="p",
        timestamp="05-07-2026_21:42:00",
        source="chat",
        entry_type="chat_pair",
        user_text="hi",
        assistant_text="hello",
    )
    plain = generate_memory_id(**base)
    routed = generate_memory_id(**base, route="QUESTION", semantic_handle="topic")
    # route + semantic_handle enter the hash payload, changing the digest.
    assert plain != routed


def test_generate_memory_id_dream_output_payload_varies():
    base = dict(
        project_id="p",
        timestamp="05-07-2026_21:42:00",
        source="dream",
        entry_type="dream_output",
        dream_output_type="idea",
        accepted_item_id="acc1",
        origin_memory_ids=["mem_a", "", "mem_b"],
        dream_content="dreamt content",
    )
    first = generate_memory_id(**base)
    # Changing dream_content changes the digest.
    second = generate_memory_id(**{**base, "dream_content": "different"})
    assert first != second
    assert first.startswith("mem_20260507_214200_")


# --- split_pair_text ------------------------------------------------------


def test_split_pair_text_with_delimiter():
    user, assistant = split_pair_text("User: hello\nAssistant: hi there")
    assert user == "hello"
    assert assistant == "hi there"


def test_split_pair_text_without_delimiter_treats_all_as_assistant():
    user, assistant = split_pair_text("just some text")
    assert user == ""
    assert assistant == "just some text"


# --- topics_to_list -------------------------------------------------------


def test_topics_to_list_none_empty():
    assert topics_to_list(None) == []
    assert topics_to_list("   ") == []


def test_topics_to_list_existing_list_cleaned():
    assert topics_to_list(["a", " b ", "", None]) == ["a", "b"]


def test_topics_to_list_scalar_splits_on_separators():
    assert topics_to_list("alpha, beta; gamma") == ["alpha", "beta", "gamma"]


# --- entry_type_label -----------------------------------------------------


def test_entry_type_label_default_and_titlecase():
    assert entry_type_label("dream_output") == "Dream Output"
    assert entry_type_label(None) == "Memory Entry"
    assert entry_type_label("   ") == "Memory Entry"  # blank after strip


# --- snake_case_value -----------------------------------------------------


def test_snake_case_value_empty_returns_empty():
    assert snake_case_value("") == ""
    assert snake_case_value(None) == ""


# --- render_artifact_header / ensure_artifact_header ----------------------


def test_render_artifact_header_shape():
    header = render_artifact_header(
        artifact_type="daily_memory", project_id="p", memory_date="05-07-2026"
    )
    assert header.startswith("---\n")
    assert "syx_artifact_type: daily_memory" in header
    assert "format_version: 1" in header
    assert "# Daily Memory: 05-07-2026" in header


def test_ensure_artifact_header_prepends_when_missing():
    out = ensure_artifact_header(
        "body content", artifact_type="daily_memory", project_id="p", memory_date="05-07-2026"
    )
    assert out.startswith("---\n")
    assert out.rstrip().endswith("body content")


def test_ensure_artifact_header_passes_through_existing_header():
    existing = (
        render_artifact_header(
            artifact_type="daily_memory", project_id="p", memory_date="05-07-2026"
        )
        + "body"
    )
    out = ensure_artifact_header(
        existing, artifact_type="daily_memory", project_id="p", memory_date="05-07-2026"
    )
    assert out.count("syx_artifact_type:") == 1  # not duplicated


def test_normalize_legacy_artifact_wrappers_converts_to_header():
    legacy = "=== BEGIN DAILY MEMORY: 05/07/2026 ===\nbody\n=== END DAILY MEMORY: 05/07/2026 ===\n"
    out = normalize_legacy_artifact_wrappers(legacy, artifact_type="daily_memory", project_id="p")
    assert out.startswith("---\n")
    assert "memory_date: 05-07-2026" in out  # date derived from the legacy wrapper
    assert "=== BEGIN DAILY MEMORY" not in out


# --- legacy_semantic_handle / ensure_entry_headings -----------------------


def test_legacy_semantic_handle_absent_returns_none():
    assert legacy_semantic_handle("no directive here") is None


def test_ensure_entry_headings_no_entries_returns_normalized():
    text = "plain text, no bounded entries\n"
    assert ensure_entry_headings(text) == text


# --- render_yaml_block ----------------------------------------------------


def test_render_yaml_block_handles_none_bool_and_list():
    block = render_yaml_block({"skip": None, "flag": True, "topics": ["a", "b"], "name": "x"})
    assert "skip:" not in block  # None dropped
    assert "flag: true" in block  # bool lowercased
    assert "topics:\n  - a\n  - b" in block
    assert "name: x" in block


# --- render_memory_entry (body_text branch) -------------------------------


def test_render_memory_entry_uses_body_text_when_provided():
    out = render_memory_entry(
        memory_id="mem_20260507_214200_a8f3",
        metadata={"entry_type": "dream_output"},
        body_text="pre-rendered body",
    )
    assert "pre-rendered body" in out
    assert "### User Message" not in out  # body_text replaces user/assistant


# --- _parse_scalar --------------------------------------------------------


def test_parse_scalar_booleans_and_strings():
    assert _parse_scalar("true") is True
    assert _parse_scalar("False") is False
    assert _parse_scalar("  some text ") == "some text"


# --- parse_yaml_metadata_with_warnings ------------------------------------


def _meta_entry(body_lines):
    return "\n".join(["### Syx Metadata", "", "```yaml", *body_lines, "```"])


def test_parse_yaml_metadata_scalars_and_lists():
    meta, warnings = parse_yaml_metadata_with_warnings(
        _meta_entry(["entry_type: chat_pair", "topics:", "  - a", "  - b", "keep: true"])
    )
    assert warnings == []
    assert meta["entry_type"] == "chat_pair"
    assert meta["topics"] == ["a", "b"]
    assert meta["keep"] is True


def test_parse_yaml_metadata_invalid_fence():
    text = "### Syx Metadata\nnot-blank\n```yaml\nkey: v\n```"
    meta, warnings = parse_yaml_metadata_with_warnings(text)
    assert meta == {}
    assert any("invalid Syx metadata fence" in w for w in warnings)


def test_parse_yaml_metadata_missing_colon_and_empty_key_and_blank_lines():
    meta, warnings = parse_yaml_metadata_with_warnings(
        _meta_entry(["", "no_colon_here", ": no key", "ok: value"])
    )
    assert meta == {"ok": "value"}
    assert any("missing ':'" in w for w in warnings)
    assert any("empty key" in w for w in warnings)


def test_parse_yaml_metadata_missing_closing_fence():
    # Block never closes with ``` -> warning about missing closing fence.
    text = "### Syx Metadata\n\n```yaml\nkey: value\n"
    meta, warnings = parse_yaml_metadata_with_warnings(text)
    assert meta == {"key": "value"}
    assert any("missing closing fence" in w for w in warnings)


def test_parse_yaml_metadata_no_block_returns_empty():
    assert parse_yaml_metadata_with_warnings("no metadata here") == ({}, [])


def test_parse_yaml_metadata_discards_warnings():
    meta = parse_yaml_metadata(_meta_entry(["entry_type: note"]))
    assert meta == {"entry_type": "note"}


# --- parse_syx_entries structural warnings --------------------------------


def test_parse_syx_entries_invalid_begin_marker():
    # Loose begin (id not matching the strict pattern) -> invalid begin warning.
    text = "<!-- begin syx:memory_id=not-valid-id -->\nbody\n"
    result = parse_syx_entries(text)
    assert any("invalid begin marker" in w for w in result.structural_warnings)


def test_parse_syx_entries_end_without_begin():
    text = "<!-- end syx:memory_id=mem_20260507_214200_a8f3 -->\n"
    result = parse_syx_entries(text)
    assert any("end without begin" in w for w in result.structural_warnings)


def test_parse_syx_entries_invalid_end_marker():
    text = "<!-- end syx:memory_id=loose-id -->\n"
    result = parse_syx_entries(text)
    assert any("invalid end marker" in w for w in result.structural_warnings)


def test_parse_syx_entries_records_artifact_path_default():
    mid = "mem_20260507_214200_a8f3"
    text = f"<!-- begin syx:memory_id={mid} -->\nbody\n<!-- end syx:memory_id={mid} -->\n"
    result = parse_syx_entries(text, artifact_path="memory/p/daily.md")
    assert result.entries[0].metadata["artifact_path"] == "memory/p/daily.md"


def test_parse_syx_entries_mismatched_end_marker():
    begin_id = "mem_20260507_214200_a8f3"
    other_id = "mem_20260507_214201_b8f3"
    text = (
        f"<!-- begin syx:memory_id={begin_id} -->\n"
        "body\n"
        f"<!-- end syx:memory_id={other_id} -->\n"
    )
    result = parse_syx_entries(text)
    assert any("mismatched end marker" in w for w in result.structural_warnings)
    assert result.entries == []  # mismatch is not a completed entry


# --- replace_current_scope_for_ltm (no entries) ---------------------------


def test_replace_current_scope_no_entries_returns_unchanged():
    text = "plain text with no bounded entries\n"
    assert replace_current_scope_for_ltm(text) == text


# --- unbounded_regions ----------------------------------------------------


def test_unbounded_regions_no_occupied_returns_whole_text():
    assert unbounded_regions("hello", []) == ["hello"]
    assert unbounded_regions("   ", []) == []  # whitespace-only -> nothing


def test_unbounded_regions_returns_gaps_between_and_after_ranges():
    text = "AAAAABBBBBCCCCC"  # 15 chars
    # Occupied: [5,10) (the B run). Leading A run and trailing C run are gaps.
    regions = unbounded_regions(text, [(5, 10)])
    assert regions == ["AAAAA", "CCCCC"]


def test_unbounded_regions_skips_whitespace_only_gaps():
    text = "AAAAA     CCCCC"
    # Occupied covers everything except a whitespace-only middle -> no regions.
    regions = unbounded_regions(text, [(0, 5), (10, 15)])
    assert regions == []
