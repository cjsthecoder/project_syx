"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from backend.app.rag.chunk_utils import collapse_snippet_groups


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
