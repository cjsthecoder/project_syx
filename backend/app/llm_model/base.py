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
    prompt_tokens_reported: int
    completion_tokens_reported: int
    total_tokens_reported: int
    usage_is_estimate: bool
    extra_usage: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: LLMUsage


class LLMChatClient(Protocol):
    def generate_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> LLMResponse:
        ...

    def stream_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Iterable[Tuple[str, Optional[LLMUsage]]]:
        ...


class LLMResponsesClient(Protocol):
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
        ...
