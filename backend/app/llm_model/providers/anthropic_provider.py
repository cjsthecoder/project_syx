"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Anthropic-backed implementation for the provider-agnostic LLM client boundary.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from anthropic import Anthropic

from ..base import LLMResponse, LLMUsage, Message

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_ANTHROPIC_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def _as_mapping(value: Any) -> Dict[str, Any]:
    """Coerce an SDK envelope or dict into a plain mapping."""
    if isinstance(value, dict):
        return value
    try:
        dumped = getattr(value, "model_dump", None)
        if callable(dumped):
            data = dumped(mode="python")
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("anthropic_provider model_dump parse skipped detail=%s", exc)
    return {}


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion used for provider usage envelopes."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default)


def _content_text(value: Any) -> str:
    """Flatten Anthropic content blocks into assistant text."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""

    out: List[str] = []
    for item in value:
        item_type = getattr(item, "type", None) or _as_mapping(item).get("type")
        text = getattr(item, "text", None)
        if text is None:
            text = _as_mapping(item).get("text")
        if item_type == "text" and isinstance(text, str):
            out.append(text)
    return "".join(out)


def _usage_from_message(usage: Any) -> LLMUsage:
    """Normalize Anthropic Messages API usage into ``LLMUsage``."""
    try:
        usage_map = _as_mapping(usage)
        prompt = _coerce_int(
            getattr(usage, "input_tokens", None),
            _coerce_int(usage_map.get("input_tokens", 0)),
        )
        completion = _coerce_int(
            getattr(usage, "output_tokens", None),
            _coerce_int(usage_map.get("output_tokens", 0)),
        )
        extra: Dict[str, Any] = {}
        for field in (
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "server_tool_use",
        ):
            value = getattr(usage, field, None)
            if value is None:
                value = usage_map.get(field)
            if value is not None:
                extra[field] = value
        return LLMUsage(
            prompt_tokens_reported=prompt,
            completion_tokens_reported=completion,
            total_tokens_reported=prompt + completion,
            usage_is_estimate=False,
            extra_usage=extra or None,
        )
    except Exception as exc:
        logger.warning(
            "anthropic_provider usage parse failed; operation=_usage_from_message detail=%s",
            exc,
        )
        return LLMUsage(
            prompt_tokens_reported=0,
            completion_tokens_reported=0,
            total_tokens_reported=0,
            usage_is_estimate=True,
        )


def _split_messages(messages: List[Message]) -> tuple[Optional[str], List[Message]]:
    """Split system messages into Anthropic's dedicated system parameter."""
    system_parts: List[str] = []
    chat_messages: List[Message] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role in {"user", "assistant"}:
            chat_messages.append({"role": role, "content": content})
    return ("\n\n".join(system_parts) or None), chat_messages


def _messages_from_prompts(
    system_prompt: Optional[str], user_prompt: str
) -> tuple[Optional[str], List[Message]]:
    """Build Anthropic system/messages parameters from response-style prompts."""
    return (
        str(system_prompt) if system_prompt else None,
        [{"role": "user", "content": str(user_prompt)}],
    )


def _anthropic_max_tokens(max_tokens: Optional[int]) -> int:
    """Return a valid Anthropic max_tokens value."""
    if max_tokens is None:
        return _DEFAULT_MAX_TOKENS
    return max(1, int(max_tokens))


def _anthropic_temperature(temperature: Optional[float]) -> Optional[float]:
    """Clamp optional temperature to Anthropic's supported range."""
    if temperature is None:
        return None
    return max(0.0, min(1.0, float(temperature)))


def _anthropic_thinking(reasoning_effort: Optional[str]) -> Optional[Dict[str, Any]]:
    """Map provider-agnostic reasoning effort to Anthropic's effort parameter."""
    if not reasoning_effort:
        return None
    return {"type": "adaptive", "effort": str(reasoning_effort)}


class AnthropicLLMProvider:
    """LLM client backed by Anthropic's Messages API.

    Implements the shared ``LLMClient`` protocol by normalizing Anthropic
    message, streaming, usage, and server-tool envelopes into Syx's provider-
    agnostic response types.
    """

    def __init__(self, *, api_key: str, default_model: str, timeout_s: float) -> None:
        """Construct the provider and initialize the Anthropic SDK client.

        Args:
            api_key: Anthropic API key used to authenticate requests.
            default_model: Model used when a request does not specify one.
            timeout_s: Per-request timeout in seconds.
        """
        self._timeout_s = float(timeout_s)
        self._client = Anthropic(api_key=api_key, timeout=self._timeout_s)
        self._default_model = str(default_model)

    def _create_message(
        self,
        *,
        model: Optional[str],
        system: Optional[str],
        messages: List[Message],
        max_tokens: Optional[int],
        temperature: Optional[float],
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Any:
        """Create an Anthropic message with shared kwargs and fallbacks."""
        kwargs: Dict[str, Any] = {
            "model": str(model or self._default_model),
            "messages": messages,
            "max_tokens": _anthropic_max_tokens(max_tokens),
        }
        if system:
            kwargs["system"] = system
        clamped_temperature = _anthropic_temperature(temperature)
        if clamped_temperature is not None:
            kwargs["temperature"] = clamped_temperature
        if tools:
            kwargs["tools"] = tools
        thinking = _anthropic_thinking(reasoning_effort)
        if thinking:
            kwargs["thinking"] = thinking

        try:
            return self._client.messages.create(**kwargs)
        except Exception as exc:
            detail = str(exc).lower()
            if "temperature" in detail and "temperature" in kwargs:
                kwargs.pop("temperature", None)
                return self._client.messages.create(**kwargs)
            if "thinking" in detail and "thinking" in kwargs:
                kwargs.pop("thinking", None)
                return self._client.messages.create(**kwargs)
            raise

    def generate_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate a chat completion via Anthropic Messages."""
        system, chat_messages = _split_messages(messages)
        resp = self._create_message(
            model=model,
            system=system,
            messages=chat_messages,
            max_tokens=max_completion_tokens,
            temperature=temperature,
        )
        return LLMResponse(
            text=_content_text(getattr(resp, "content", None)),
            model=str(model or self._default_model),
            usage=_usage_from_message(getattr(resp, "usage", None)),
        )

    def stream_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Iterable[Tuple[str, Optional[LLMUsage]]]:
        """Stream a chat completion as ``(text_delta, usage)`` tuples."""
        system, chat_messages = _split_messages(messages)
        kwargs: Dict[str, Any] = {
            "model": str(model or self._default_model),
            "messages": chat_messages,
            "max_tokens": _anthropic_max_tokens(max_completion_tokens),
            "stream": True,
        }
        if system:
            kwargs["system"] = system
        clamped_temperature = _anthropic_temperature(temperature)
        if clamped_temperature is not None:
            kwargs["temperature"] = clamped_temperature

        try:
            stream = self._client.messages.create(**kwargs)
        except Exception as exc:
            if "temperature" in str(exc).lower() and "temperature" in kwargs:
                kwargs.pop("temperature", None)
                stream = self._client.messages.create(**kwargs)
            else:
                raise

        input_tokens = 0
        output_tokens = 0
        for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                text = getattr(delta, "text", None)
                if isinstance(text, str) and text:
                    yield text, None
            elif event_type == "message_delta":
                usage = getattr(event, "usage", None)
                if usage is not None:
                    output_tokens = _usage_from_message(usage).completion_tokens_reported
            elif event_type == "message_start":
                usage = getattr(getattr(event, "message", None), "usage", None)
                if usage is not None:
                    input_tokens = _usage_from_message(usage).prompt_tokens_reported
        if input_tokens or output_tokens:
            yield "", LLMUsage(
                prompt_tokens_reported=input_tokens,
                completion_tokens_reported=output_tokens,
                total_tokens_reported=input_tokens + output_tokens,
                usage_is_estimate=False,
            )

    def generate_response(
        self,
        *,
        model: Optional[str],
        system_prompt: Optional[str],
        user_prompt: str,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        require_json_object: bool = False,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """Generate a prompt/response completion via Anthropic Messages."""
        system, messages = _messages_from_prompts(system_prompt, user_prompt)
        response_prompt = str(user_prompt)
        if require_json_object:
            response_prompt += "\n\nReturn only a valid JSON object. Do not include markdown."
            messages = [{"role": "user", "content": response_prompt}]
        resp = self._create_message(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_output_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        return LLMResponse(
            text=_content_text(getattr(resp, "content", None)).strip(),
            model=str(model or self._default_model),
            usage=_usage_from_message(getattr(resp, "usage", None)),
        )

    def generate_response_research(
        self,
        *,
        model: Optional[str],
        system_prompt: Optional[str],
        user_prompt: str,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """Generate a response with Anthropic server-side web search enabled."""
        system, messages = _messages_from_prompts(system_prompt, user_prompt)
        resp = self._create_message(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_output_tokens,
            temperature=temperature,
            tools=[_ANTHROPIC_WEB_SEARCH_TOOL],
        )
        return LLMResponse(
            text=_content_text(getattr(resp, "content", None)).strip(),
            model=str(model or self._default_model),
            usage=_usage_from_message(getattr(resp, "usage", None)),
        )
