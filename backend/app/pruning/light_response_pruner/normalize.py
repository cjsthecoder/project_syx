"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Text normalization helpers for prefix matching.

Provides a single helper that lowercases, collapses whitespace, and strips
trailing punctuation so text can be compared against pruning rule prefixes.
"""

import re

_TRAILING_SENTENCE_PUNCTUATION_RE = re.compile(r"[.!?]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_prefix_match(text: str) -> str:
    """Normalize text for case- and punctuation-insensitive prefix matching.

    Lowercases, converts curly apostrophes to straight ones, collapses runs of
    whitespace to single spaces, and strips trailing sentence punctuation.

    Args:
        text: Text to normalize.

    Returns:
        The normalized comparison string.
    """
    normalized = text.lower()
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = normalized.strip()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = _TRAILING_SENTENCE_PUNCTUATION_RE.sub("", normalized)
    return normalized.strip()

