"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for ChatGPT HTML export message extraction.

These tests cover the extraction helpers in
``tools.import_chat_html_to_markdown_memory``, verifying USER/ASSISTANT
parsing from legacy role-tagged divs and the conversation-turn fallback,
plus detection of incomplete or virtualized HTML dumps.
"""
from pathlib import Path
import sys

from bs4 import BeautifulSoup  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.import_chat_html_to_markdown_memory import (
    _extract_messages_with_diagnostics,
    _html_appears_incomplete_or_virtualized,
)


def test_extracts_legacy_role_tagged_messages():
    html = """
    <main>
      <div data-message-author-role="user"><p>Hello <em>there</em></p></div>
      <div data-message-author-role="assistant"><p>General Kenobi</p></div>
    </main>
    """

    result = _extract_messages_with_diagnostics(html, BeautifulSoup)

    assert result.messages == [("USER", "Hello\nthere"), ("ASSISTANT", "General Kenobi")]
    assert result.diagnostics["extractor"] == "role_tagged"
    assert result.diagnostics["role_tagged_messages_total"] == 2
    assert result.diagnostics["selected_user_turns"] == 1
    assert result.diagnostics["selected_assistant_turns"] == 1


def test_conversation_turn_fallback_extracts_changed_chatgpt_html():
    html = """
    <main>
      <div data-testid="conversation-turn-1">You said: First prompt</div>
      <div data-testid="conversation-turn-2">ChatGPT said: First answer</div>
      <div data-testid="conversation-turn-3">
        <div aria-label="Your message actions"></div>
        You said: Second prompt
      </div>
      <div data-testid="conversation-turn-4">
        <div aria-label="Response actions"></div>
        ChatGPT said: Second answer
      </div>
    </main>
    """

    result = _extract_messages_with_diagnostics(html, BeautifulSoup)

    assert result.messages == [
        ("USER", "First prompt"),
        ("ASSISTANT", "First answer"),
        ("USER", "Second prompt"),
        ("ASSISTANT", "Second answer"),
    ]
    assert result.diagnostics["extractor"] == "conversation_turn"
    assert result.diagnostics["conversation_turns_total"] == 4
    assert result.diagnostics["conversation_turns_user"] == 2
    assert result.diagnostics["conversation_turns_assistant"] == 2


def test_conversation_turn_fallback_skips_empty_and_placeholder_turns():
    html = """
    <main>
      <div data-testid="conversation-turn-1"></div>
      <div data-testid="conversation-turn-2">ChatGPT said: Stopped thinking Edit</div>
      <div data-testid="conversation-turn-3">You said: Real prompt</div>
      <div data-testid="conversation-turn-4">ChatGPT said: Real answer</div>
    </main>
    """

    result = _extract_messages_with_diagnostics(html, BeautifulSoup)

    assert result.messages == [("USER", "Real prompt"), ("ASSISTANT", "Real answer")]
    assert result.diagnostics["conversation_turns_empty"] == 1
    assert result.diagnostics["conversation_turns_placeholder_assistant"] == 1
    assert result.diagnostics["conversation_turns_nonempty"] == 3


def test_detects_incomplete_virtualized_html():
    diagnostics = {
        "conversation_turns_empty": 505,
        "selected_user_turns": 19,
        "selected_assistant_turns": 3,
    }

    assert _html_appears_incomplete_or_virtualized(diagnostics)
