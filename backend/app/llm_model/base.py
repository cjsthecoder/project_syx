"""
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
    """Token usage reported (or estimated) for a single LLM call.

    Attributes:
        prompt_tokens_reported: Prompt/input tokens as reported by the backend.
        completion_tokens_reported: Completion/output tokens reported.
        total_tokens_reported: Total tokens reported for the call.
        usage_is_estimate: True when the counts were estimated locally because
            the backend did not return usage data.
        extra_usage: Optional backend-specific usage details (e.g. cached or
            reasoning token breakdowns).
    """

    prompt_tokens_reported: int
    completion_tokens_reported: int
    total_tokens_reported: int
    usage_is_estimate: bool
    extra_usage: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """Result envelope for an LLM call.

    Attributes:
        text: Generated completion text.
        model: Identifier of the model that produced the response.
        usage: Token usage for the call.
    """

    text: str
    model: str
    usage: LLMUsage


class LLMChatClient(Protocol):
    """Contract for chat-completions-style LLM backends.

    Boundary used by application code to generate and stream chat completions
    independent of the concrete provider, normalizing results into
    ``LLMResponse``/``LLMUsage``.
    """

    def generate_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate a single chat completion and return it as an ``LLMResponse``.

        Args:
            messages: Chat messages in role/content form.
            model: Optional model override; defaults to the backend's default.
            temperature: Optional sampling temperature.
            max_completion_tokens: Optional cap on generated tokens.

        Returns:
            An ``LLMResponse`` with the completion text, model, and token usage.
        """
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

        Args:
            messages: Chat messages in role/content form.
            model: Optional model override; defaults to the backend's default.
            temperature: Optional sampling temperature.
            max_completion_tokens: Optional cap on generated tokens.

        Yields:
            Tuples of a text delta and an optional usage payload.
        """
        ...


class LLMResponsesClient(Protocol):
    """Contract for OpenAI Responses-API-style LLM backends.

    Boundary for system/user prompt generation with optional reasoning effort,
    strict JSON-object output, and tool definitions, returning the normalized
    ``LLMResponse``. Used by the tagger/builder and dream pipelines.
    """

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

        Args:
            model: Optional model override; defaults to the backend's default.
            system_prompt: Optional system instructions.
            user_prompt: User prompt text.
            max_output_tokens: Optional cap on generated tokens.
            reasoning_effort: Optional reasoning effort hint (e.g., "low").
            require_json_object: When True, request a strict JSON-object response.
            tools: Optional tool definitions to expose to the model.
            temperature: Optional sampling temperature.

        Returns:
            An ``LLMResponse`` with the output text, model, and token usage.
        """
        ...
