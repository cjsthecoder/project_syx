"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for the RAG chunk utilities.

Covers deterministic character splitting (split_text_simple), adjacent
same-document overlap trimming (trim_adjacent_chunk_overlap), and snippet-group
collapsing (collapse_snippet_groups) including sparse/legacy and non-dict edges.
"""
from app.rag.chunk_utils import (
    collapse_snippet_groups,
    split_text_simple,
    trim_adjacent_chunk_overlap,
)


def _chunk(text: str, idx: int, *, source_document_id: str = "doc") -> dict:
    return {
        "source": "ltm",
        "score": 0.9,
        "text": text,
        "metadata": {
            "source_document_id": source_document_id,
            "chunk_index": idx,
        },
    }


def test_collapse_snippet_groups_concatenates_adjacent_chunks_without_inserted_newline():
    collapsed = collapse_snippet_groups(
        [
            _chunk("*** ASSIS", 0),
            _chunk("TANT (data-message-author-role: assistant) ***", 1),
        ]
    )

    assert len(collapsed) == 1
    assert collapsed[0]["text"] == "*** ASSISTANT (data-message-author-role: assistant) ***"
    assert collapsed[0]["metadata"]["chunk_index"] == "0..1"


def test_collapse_snippet_groups_splits_non_contiguous_chunks():
    collapsed = collapse_snippet_groups(
        [
            _chunk("first", 0),
            _chunk("third", 2),
        ]
    )

    assert len(collapsed) == 2
    assert collapsed[0]["text"] == "first"
    assert collapsed[0]["metadata"]["chunk_index"] == 0
    assert collapsed[1]["text"] == "third"
    assert collapsed[1]["metadata"]["chunk_index"] == 2


def test_collapse_snippet_groups_empty_returns_empty():
    assert collapse_snippet_groups([]) == []


def test_collapse_snippet_groups_non_dict_flushes_group():
    collapsed = collapse_snippet_groups([_chunk("a", 0), "garbage", _chunk("b", 0)])
    # The non-dict entry flushes the open group and is itself dropped.
    assert [c["text"] for c in collapsed] == ["a", "b"]


def test_collapse_snippet_groups_leading_non_dict_flushes_empty_group():
    # A non-dict first entry triggers a flush with no open group (no-op), then
    # the real chunk is emitted.
    collapsed = collapse_snippet_groups(["garbage", _chunk("a", 0)])
    assert [c["text"] for c in collapsed] == ["a"]


def test_collapse_snippet_groups_sparse_chunk_stands_alone():
    sparse = {"source": "ltm", "score": 0.5, "text": "sparse", "metadata": {}}
    collapsed = collapse_snippet_groups([_chunk("a", 0), sparse, _chunk("b", 1)])
    # Sparse chunk (no source_document_id) never merges; it is emitted standalone
    # and also breaks the run so "a" and "b" do not collapse together.
    assert [c["text"] for c in collapsed] == ["a", "sparse", "b"]


# --- split_text_simple ----------------------------------------------------


def test_split_text_simple_basic_windows_with_overlap():
    out = split_text_simple("abcdef", chunk_size=4, chunk_overlap=2)
    # step = 4 - 2 = 2 -> windows at 0,2,4: "abcd","cdef","ef".
    assert out == ["abcd", "cdef", "ef"]


def test_split_text_simple_no_overlap():
    out = split_text_simple("abcdef", chunk_size=3, chunk_overlap=0)
    assert out == ["abc", "def"]


def test_split_text_simple_non_positive_chunk_size_returns_empty():
    assert split_text_simple("abcdef", chunk_size=0, chunk_overlap=0) == []
    assert split_text_simple("abcdef", chunk_size=-5, chunk_overlap=0) == []


def test_split_text_simple_overlap_clamped_below_chunk_size():
    # overlap >= chunk_size is clamped to chunk_size - 1 so progress is guaranteed.
    out = split_text_simple("abcde", chunk_size=2, chunk_overlap=5)
    # ov clamped to 1 -> step 1 -> windows of width 2 at each index.
    assert out == ["ab", "bc", "cd", "de", "e"]


def test_split_text_simple_drops_whitespace_only_windows():
    out = split_text_simple("a       b", chunk_size=3, chunk_overlap=0)
    # Middle window "   " is whitespace-only and dropped.
    assert all(w.strip() for w in out)
    assert "a" in out[0]


def test_split_text_simple_none_text_returns_empty():
    assert split_text_simple(None, chunk_size=4, chunk_overlap=1) == []


# --- trim_adjacent_chunk_overlap ------------------------------------------


def _ov_chunk(text: str, *, sid="doc") -> dict:
    return {"text": text, "metadata": {"source_document_id": sid}}


def test_trim_overlap_noop_on_empty_or_nonpositive_overlap():
    chunks = [_ov_chunk("abc"), _ov_chunk("cde")]
    trim_adjacent_chunk_overlap(chunks, 0)  # disabled
    assert chunks[1]["text"] == "cde"
    trim_adjacent_chunk_overlap([], 5)  # empty -> no error


def test_trim_overlap_removes_shared_prefix_same_document():
    chunks = [_ov_chunk("hello world"), _ov_chunk("world peace")]
    trim_adjacent_chunk_overlap(chunks, 10)
    # Longest suffix/prefix overlap is "world" -> removed from B.
    assert chunks[1]["text"] == " peace"


def test_trim_overlap_skips_different_documents():
    chunks = [_ov_chunk("hello world", sid="d1"), _ov_chunk("world peace", sid="d2")]
    trim_adjacent_chunk_overlap(chunks, 10)
    assert chunks[1]["text"] == "world peace"  # unchanged across documents


def test_trim_overlap_skips_non_dict_entries():
    chunks = [_ov_chunk("abc"), "garbage"]
    trim_adjacent_chunk_overlap(chunks, 5)  # must not raise
    assert chunks[0]["text"] == "abc"


def test_trim_overlap_leaves_b_unchanged_when_no_overlap():
    chunks = [_ov_chunk("abc"), _ov_chunk("xyz")]
    trim_adjacent_chunk_overlap(chunks, 5)
    assert chunks[1]["text"] == "xyz"


def test_trim_overlap_does_not_empty_b():
    # Full text of B equals the overlap; trimming would empty B, so leave it.
    chunks = [_ov_chunk("xxabc"), _ov_chunk("abc")]
    trim_adjacent_chunk_overlap(chunks, 5)
    assert chunks[1]["text"] == "abc"


def test_trim_overlap_skips_when_a_chunk_text_empty():
    # An empty text makes max_overlap 0 -> the pair is skipped without error.
    chunks = [_ov_chunk(""), _ov_chunk("abc")]
    trim_adjacent_chunk_overlap(chunks, 5)
    assert chunks[1]["text"] == "abc"
