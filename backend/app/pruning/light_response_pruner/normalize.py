"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from __future__ import annotations

import re

_TRAILING_SENTENCE_PUNCTUATION_RE = re.compile(r"[.!?]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_prefix_match(text: str) -> str:
    normalized = text.lower()
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = normalized.strip()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = _TRAILING_SENTENCE_PUNCTUATION_RE.sub("", normalized)
    return normalized.strip()

