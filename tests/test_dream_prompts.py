"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for the Dream-cycle prompt builders.

These are pure f-string templates; the tests assert each builder runs and
interpolates its inputs into the returned prompt.
"""

from app.dream.agents.prompts.idea_prompts import build_idea_prompt
from app.dream.agents.prompts.questions_prompts import (
    build_answer_question_prompt_local,
    build_answer_question_prompt_remote,
)
from app.dream.agents.prompts.research_prompts import build_research_prompt
from app.dream.prompts import build_project_summary_prompt


def test_build_project_summary_prompt_interpolates_context():
    out = build_project_summary_prompt("CTX-123")
    assert "CTX-123" in out and "Syx Dream Cycle" in out


def test_build_idea_prompt_interpolates_context():
    out = build_idea_prompt("DREAM-CTX")
    assert "DREAM-CTX" in out and "Idea Agent" in out


def test_build_answer_question_prompt_local():
    out = build_answer_question_prompt_local("Q?", "topicX", "localCTX")
    assert "Q?" in out and "topicX" in out and "localCTX" in out


def test_build_answer_question_prompt_remote():
    out = build_answer_question_prompt_remote("Q?", "topicX", "localCTX", "remoteCTX")
    assert "Q?" in out and "remoteCTX" in out and "Remote Research" in out


def test_build_research_prompt():
    out = build_research_prompt(
        "summary",
        "localctx",
        "origin",
        "Open Question",
        "assist",
        "topicZ",
        "themeY",
    )
    assert "topicZ" in out and "themeY" in out and "Researcher Agent" in out
