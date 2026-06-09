"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.agent_interface.parser.

Exercises the prompt-context parser's helpers directly (header/YAML metadata,
scalar coercion, chunk-index parsing, topics/page normalization) plus the
round-trip renderer. The parser only depends on the pydantic snippet model, so
these are pure, fast unit tests.
"""

from app.agent_interface import parser as P
from app.agent_interface.models import AgentMemorySnippet

# --- SnippetParseError ----------------------------------------------------


def test_snippet_parse_error_retains_raw_context():
    err = P.SnippetParseError("boom", raw_context="ctx")
    assert str(err) == "boom"
    assert err.raw_context == "ctx"


# --- parse_prompt_context_to_snippets edges -------------------------------


def test_parse_empty_context_returns_empty():
    assert P.parse_prompt_context_to_snippets("") == []
    assert P.parse_prompt_context_to_snippets("   ") == []


def test_parse_context_without_snippet_headers_returns_empty():
    # Non-empty body but no "Snippet N (...)" header -> no parts.
    assert P.parse_prompt_context_to_snippets("Context:\n---\njust prose, no header") == []


# --- _split_snippet_parts / _is_context_delimited_snippet_start -----------


def test_header_after_blank_lines_is_a_boundary():
    # Header preceded only by blank lines (not the first line) still counts.
    body = "\n\nSnippet 1 (source=ltm, cos=0.5000, score=0.7000, file=a.md, page=None, chunk_index=0)\nbody"
    snippets = P.parse_prompt_context_to_snippets("Context:\n---\n" + body)
    assert len(snippets) == 1
    assert snippets[0].snippet_number == 1


def test_is_context_delimited_snippet_start_cases():
    # First line is always a boundary.
    assert P._is_context_delimited_snippet_start(["Snippet 1 (...)"], 0) is True
    # Header preceded only by blank lines back to start -> boundary.
    assert P._is_context_delimited_snippet_start(["", "", "Snippet 1 (...)"], 2) is True
    # Previous non-blank line is the '---' delimiter -> boundary.
    assert P._is_context_delimited_snippet_start(["---", "Snippet 2 (...)"], 1) is True
    # ...even with intervening blank lines.
    assert P._is_context_delimited_snippet_start(["---", "", "Snippet 2 (...)"], 2) is True
    # Previous non-blank line is ordinary content -> not a boundary.
    assert P._is_context_delimited_snippet_start(["body text", "Snippet 2 (...)"], 1) is False
    assert P._is_context_delimited_snippet_start(["body text", "", "Snippet 2 (...)"], 2) is False


# --- _parse_first_yaml_block ----------------------------------------------


def test_parse_first_yaml_block_present_and_absent():
    assert P._parse_first_yaml_block("no yaml here") == {}
    body = "intro\n```yaml\nmemory_id: m1\nentry_type: chat_pair\n```\ntrailer"
    out = P._parse_first_yaml_block(body)
    assert out == {"memory_id": "m1", "entry_type": "chat_pair"}


# --- _strip_context_prefix ------------------------------------------------


def test_strip_context_prefix_crlf():
    text = "Context:\r\n---\r\nSnippet 1 (source=ltm, cos=0.5000, score=0.7000, file=a.md, page=None, chunk_index=0)\nbody"
    snippets = P.parse_prompt_context_to_snippets(text)
    assert len(snippets) == 1


def test_strip_context_prefix_passthrough_when_absent():
    assert P._strip_context_prefix("no prefix here") == "no prefix here"


# --- _parse_part ----------------------------------------------------------


def test_parse_part_empty_returns_none():
    assert P._parse_part("") is None


def test_parse_part_without_header_returns_none():
    assert P._parse_part("not a header line\nsome body") is None


# --- _parse_header_meta ---------------------------------------------------


def test_parse_header_meta_skips_pieces_without_equals():
    out = P._parse_header_meta("source=ltm, garbage, score=0.8")
    assert out == {"source": "ltm", "score": "0.8"}


# --- _parse_simple_yaml ---------------------------------------------------


def test_parse_simple_yaml_skips_comments_and_keyless_lines():
    raw = "# a comment\n\nkeyless line\nkey: value\n:novalue\n"
    out = P._parse_simple_yaml(raw)
    assert out == {"key": "value"}  # comment, keyless, and empty-key lines skipped


def test_parse_simple_yaml_block_list():
    raw = "topics:\n  - one\n  - two\nname: x\n"
    out = P._parse_simple_yaml(raw)
    assert out == {"topics": ["one", "two"], "name": "x"}


# --- _clean_scalar --------------------------------------------------------


def test_clean_scalar_variants():
    assert P._clean_scalar("") == ""
    assert P._clean_scalar('"quoted"') == "quoted"
    assert P._clean_scalar("'single'") == "single"
    assert P._clean_scalar("null") is None
    assert P._clean_scalar("true") is True
    assert P._clean_scalar("false") is False
    assert P._clean_scalar("[]") == []
    assert P._clean_scalar("[a, b]") == ["a", "b"]
    assert P._clean_scalar("42") == 42
    assert P._clean_scalar("-7") == -7
    assert P._clean_scalar("plain text") == "plain text"


# --- _parse_chunk_index ---------------------------------------------------


def test_parse_chunk_index_variants():
    assert P._parse_chunk_index(None) == (None, None, None)
    assert P._parse_chunk_index("") == (None, None, None)
    assert P._parse_chunk_index("5") == (5, 5, "5")
    assert P._parse_chunk_index("3..7") == (3, 7, "3..7")
    # Unparseable range -> None range string but parsed ends still attempted.
    assert P._parse_chunk_index("a..b") == (None, None, None)
    # Non-numeric single -> all None.
    assert P._parse_chunk_index("abc") == (None, None, None)


# --- _source_document_id --------------------------------------------------


def test_source_document_id_resolution():
    assert P._source_document_id(explicit="x", artifact_path="a", memory_id="m") == "x"
    assert (
        P._source_document_id(explicit=None, artifact_path="a.md", memory_id="m1")
        == "a.md::memory_id=m1"
    )
    assert P._source_document_id(explicit=None, artifact_path=None, memory_id="m1") is None


# --- _topics --------------------------------------------------------------


def test_topics_normalization():
    assert P._topics(["a", " b ", ""]) == ["a", "b"]
    assert P._topics([]) is None
    assert P._topics("a, b, c") == ["a", "b", "c"]
    assert P._topics("single") == ["single"]
    assert P._topics("") is None
    assert P._topics(123) is None


# --- _parse_page ----------------------------------------------------------


def test_parse_page_variants():
    assert P._parse_page(None) is None
    assert P._parse_page("none") is None
    assert P._parse_page("  ") is None
    assert P._parse_page("12") == 12
    assert P._parse_page("xiv") == "xiv"
    assert P._parse_page(5) == 5


# --- _none_if_literal_none ------------------------------------------------


def test_none_if_literal_none():
    assert P._none_if_literal_none(None) is None
    assert P._none_if_literal_none("None") is None
    assert P._none_if_literal_none("real.md") == "real.md"


# --- _as_float / _as_int --------------------------------------------------


def test_as_float():
    assert P._as_float(None) is None
    assert P._as_float("1.5") == 1.5
    assert P._as_float("abc") is None


def test_as_int():
    assert P._as_int(None) is None
    assert P._as_int("3") == 3
    assert P._as_int("abc") is None


# --- render_prompt_text_from_snippets / _render_header --------------------


def test_render_empty_snippets_returns_empty_string():
    assert P.render_prompt_text_from_snippets([]) == ""


def test_render_roundtrips_non_daily_snippet():
    snip = AgentMemorySnippet(
        snippet_number=1,
        source="ltm",
        cos=0.6411,
        score=0.8206,
        file="sleep.md",
        page=None,
        chunk_index_start=0,
        chunk_index_end=1,
        chunk_index_range="0..1",
        text="body text",
    )
    rendered = P.render_prompt_text_from_snippets([snip])
    assert rendered.startswith("Context:\n---\n")
    assert "Snippet 1 (" in rendered
    assert "file=sleep.md" in rendered
    assert "chunk_index=0..1" in rendered
    # Round-trips back to a parseable snippet.
    reparsed = P.parse_prompt_context_to_snippets(rendered)
    assert reparsed[0].file == "sleep.md"


def test_render_daily_snippet_omits_file_and_reconstructs_chunk_range():
    # No chunk_index_range -> reconstructed from start/end; equal -> single value.
    snip = AgentMemorySnippet(
        snippet_number=2,
        source="daily",
        cos=None,
        score=None,
        chunk_index_start=4,
        chunk_index_end=4,
        text="daily body",
    )
    header = P._render_header(snip)
    assert "route=None" in header  # daily omits file/page
    assert "cos=None" in header and "score=None" in header
    assert "chunk_index=4" in header


def test_render_header_reconstructs_range_when_start_differs_from_end():
    snip = AgentMemorySnippet(
        snippet_number=3,
        source="ltm",
        cos=0.1,
        score=0.2,
        file="a.md",
        chunk_index_start=2,
        chunk_index_end=5,
        text="x",
    )
    header = P._render_header(snip)
    assert "chunk_index=2..5" in header
