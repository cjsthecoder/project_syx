"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Provider-agnostic LLM client interfaces and data envelopes.
"""


from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple


Message = Dict[str, str]


@dataclass
class LLMUsage:
    """Token usage reported (or estimated) for a single LLM call."""

    prompt_tokens_reported: int
    completion_tokens_reported: int
    total_tokens_reported: int
    usage_is_estimate: bool
    extra_usage: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """Result envelope for an LLM call: text, model used, and token usage."""

    text: str
    model: str
    usage: LLMUsage


class LLMChatClient(Protocol):
    """Contract for chat-completions-style LLM backends."""

    def generate_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate a single chat completion and return it as an ``LLMResponse``."""
        ...

    def stream_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Iterable[Tuple[str, Optional[LLMUsage]]]:
        """Stream a chat completion as ``(text_delta, usage)`` tuples.

        Each yielded tuple carries either a text chunk (with ``None`` usage) or
        a final usage payload (with an empty text chunk).
        """
        ...


class LLMResponsesClient(Protocol):
    """Contract for OpenAI Responses-API-style LLM backends."""

    def generate_response(
        self,
        *,
        model: Optional[str],
        system_prompt: Optional[str],
        user_prompt: str,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        require_json_object: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """Generate a response from a system/user prompt pair.

        Supports optional reasoning effort, strict JSON-object output, and tool
        definitions, returning the result as an ``LLMResponse``.
        """
        ...
