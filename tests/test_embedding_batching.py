"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Unit tests for app.embedding.batching.

Token estimation is replaced with a deterministic length-based stub so batch
boundaries are exact and independent of the installed tokenizer.
"""

import pytest

import app.embedding.batching as batching
from app.embedding.batching import iter_token_batches


@pytest.fixture(autouse=True)
def _deterministic_token_estimate(monkeypatch):
    # Treat each character as exactly one token for predictable boundaries.
    monkeypatch.setattr(batching, "estimate_tokens", lambda t, **_: len(t or ""))


def test_rejects_nonpositive_budget():
    with pytest.raises(ValueError):
        list(iter_token_batches(["a"], max_tokens_per_batch=0))


def test_rejects_mismatched_metadata_length():
    with pytest.raises(ValueError):
        list(
            iter_token_batches(
                ["a", "b"],
                metadatas=[{"i": 0}],
                max_tokens_per_batch=10,
            )
        )


def test_empty_input_yields_nothing():
    assert list(iter_token_batches([], max_tokens_per_batch=10)) == []


def test_oversized_single_item_is_kept_in_its_own_batch():
    batches = list(iter_token_batches(["x" * 12], max_tokens_per_batch=10))
    assert len(batches) == 1
    texts, metas, est = batches[0]
    assert texts == ["x" * 12]
    assert metas is None
    assert est == 12


def test_splits_into_batches_under_budget():
    texts = ["aaaa", "bbbb", "cc", "d" * 10, "e"]
    batches = list(iter_token_batches(texts, max_tokens_per_batch=10))
    grouped = [(t, est) for (t, _m, est) in batches]
    assert grouped == [
        (["aaaa", "bbbb", "cc"], 10),
        (["d" * 10], 10),
        (["e"], 1),
    ]


def test_metadatas_track_texts_and_are_defensively_copied():
    texts = ["aa", "bb"]
    metadatas = [{"i": 0}, {"i": 1}]
    batches = list(
        iter_token_batches(texts, metadatas=metadatas, max_tokens_per_batch=100)
    )
    assert len(batches) == 1
    out_texts, out_metas, _est = batches[0]
    assert out_texts == ["aa", "bb"]
    assert out_metas == [{"i": 0}, {"i": 1}]

    # Mutating returned metadata must not affect the caller's input.
    out_metas[0]["i"] = 999
    assert metadatas[0]["i"] == 0
