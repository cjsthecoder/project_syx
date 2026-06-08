"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.utils.tokens.

Covers token counting, token-budget trimming, message-content aggregation, and
the word-count fallback used when tiktoken is unavailable.
"""

import app.utils.tokens as tokens
from app.utils.tokens import (
    count_message_content_tokens,
    count_tokens,
    trim_to_tokens,
)


def test_count_tokens_empty_is_zero():
    assert count_tokens("") == 0


def test_count_tokens_positive_for_nonempty():
    assert count_tokens("hello world") >= 1


def test_count_tokens_grows_with_more_text():
    short = count_tokens("hello")
    long = count_tokens("hello " * 50)
    assert long > short


def test_trim_empty_returns_empty():
    assert trim_to_tokens("", 5) == ""


def test_trim_nonpositive_budget_returns_empty():
    assert trim_to_tokens("hello world", 0) == ""
    assert trim_to_tokens("hello world", -3) == ""


def test_trim_large_budget_returns_original():
    text = "the quick brown fox"
    assert trim_to_tokens(text, 100_000) == text


def test_trim_reduces_token_count():
    text = "the quick brown fox jumps over the lazy dog " * 10
    trimmed = trim_to_tokens(text, 5)
    assert count_tokens(trimmed) <= 5
    assert len(trimmed) < len(text)


def test_count_message_content_tokens_matches_joined():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    expected = count_tokens("hello\nworld")
    assert count_message_content_tokens(messages) == expected


def test_count_message_content_tokens_ignores_non_dicts_and_none_content():
    messages = [
        {"role": "user", "content": "hello"},
        "not-a-dict",
        {"role": "assistant", "content": None},
    ]
    expected = count_tokens("hello\n")
    assert count_message_content_tokens(messages) == expected


def test_count_message_content_tokens_none_messages_is_zero():
    assert count_message_content_tokens(None) == 0


def test_count_message_content_tokens_non_iterable_returns_zero():
    # An int is not iterable; the helper swallows the TypeError and returns 0.
    assert count_message_content_tokens(123) == 0


def test_word_count_fallback_when_tiktoken_missing(monkeypatch):
    monkeypatch.setattr(tokens, "tiktoken", None)
    tokens._resolve_encoding.cache_clear()
    try:
        assert count_tokens("a b c") == 3
        # With no encoder, trim cannot tokenize and returns the text unchanged.
        assert trim_to_tokens("a b c", 1) == "a b c"
    finally:
        # Drop the cached None encoder so other tests use real tiktoken again.
        tokens._resolve_encoding.cache_clear()
