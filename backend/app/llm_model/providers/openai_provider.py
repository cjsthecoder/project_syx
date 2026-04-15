"""
OpenAI-backed implementations for chat + responses APIs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openai import OpenAI

from ..base import LLMResponse, LLMUsage, Message

logger = logging.getLogger(__name__)


def _safe_usage_from_chat(usage: Any) -> LLMUsage:
    try:
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        return LLMUsage(
            prompt_tokens_reported=prompt,
            completion_tokens_reported=completion,
            total_tokens_reported=total,
            usage_is_estimate=False,
        )
    except Exception as exc:
        logger.warning("openai_provider usage parse failed; operation=_safe_usage_from_chat detail=%s", exc)
        return LLMUsage(
            prompt_tokens_reported=0,
            completion_tokens_reported=0,
            total_tokens_reported=0,
            usage_is_estimate=True,
        )


def _safe_usage_from_responses(usage: Any) -> LLMUsage:
    try:
        prompt = int(getattr(usage, "input_tokens", 0) or 0)
        completion = int(getattr(usage, "output_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        extra: Dict[str, Any] = {}
        for k in ("input_token_details", "output_token_details", "reasoning_tokens", "cached_tokens"):
            try:
                v = getattr(usage, k, None)
                if v is not None:
                    extra[k] = v
            except Exception as exc:
                logger.debug("openai_provider usage extra parse skipped field=%s detail=%s", k, exc)
        return LLMUsage(
            prompt_tokens_reported=prompt,
            completion_tokens_reported=completion,
            total_tokens_reported=total,
            usage_is_estimate=False,
            extra_usage=extra or None,
        )
    except Exception as exc:
        logger.warning("openai_provider usage parse failed; operation=_safe_usage_from_responses detail=%s", exc)
        return LLMUsage(
            prompt_tokens_reported=0,
            completion_tokens_reported=0,
            total_tokens_reported=0,
            usage_is_estimate=True,
        )


def _responses_output_text(resp: Any) -> str:
    try:
        output_text = getattr(resp, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text
    except Exception as exc:
        logger.warning("openai_provider failed reading output_text detail=%s", exc)
    out: List[str] = []
    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") != "message":
                continue
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    out.append(getattr(c, "text", "") or "")
    except Exception as exc:
        logger.warning("openai_provider failed iterating response output detail=%s", exc)
    return "".join(out).strip()


class OpenAILLMProvider:
    def __init__(self, *, api_key: str, default_model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._default_model = str(default_model)

    def generate_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": str(model or self._default_model),
            "messages": messages,
        }
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = int(max_completion_tokens)
        if temperature is not None:
            kwargs["temperature"] = float(temperature)

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if "temperature" in str(exc).lower():
                kwargs.pop("temperature", None)
                resp = self._client.chat.completions.create(**kwargs)
            else:
                raise

        text = ""
        try:
            choices = getattr(resp, "choices", []) or []
            if choices:
                msg = getattr(choices[0], "message", None)
                text = str(getattr(msg, "content", "") or "")
        except Exception as exc:
            logger.warning("openai_provider chat text parse failed detail=%s", exc)

        return LLMResponse(
            text=text,
            model=str(model or self._default_model),
            usage=_safe_usage_from_chat(getattr(resp, "usage", None)),
        )

    def stream_chat(
        self,
        *,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Iterable[Tuple[str, Optional[LLMUsage]]]:
        kwargs: Dict[str, Any] = {
            "model": str(model or self._default_model),
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = int(max_completion_tokens)
        if temperature is not None:
            kwargs["temperature"] = float(temperature)

        try:
            stream = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if "temperature" in str(exc).lower():
                kwargs.pop("temperature", None)
                stream = self._client.chat.completions.create(**kwargs)
            else:
                raise

        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield "", _safe_usage_from_chat(usage)
            try:
                choices = getattr(chunk, "choices", []) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                piece = getattr(delta, "content", None)
                if isinstance(piece, str) and piece:
                    yield piece, None
            except Exception as exc:
                logger.warning("openai_provider stream chunk parse failed detail=%s", exc)

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
        msg_input: List[Dict[str, str]] = []
        if system_prompt:
            msg_input.append({"role": "system", "content": str(system_prompt)})
        msg_input.append({"role": "user", "content": str(user_prompt)})

        kwargs: Dict[str, Any] = {
            "model": str(model or self._default_model),
            "input": msg_input,
        }
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = int(max_output_tokens)
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": str(reasoning_effort)}
        if tools:
            kwargs["tools"] = tools
        if require_json_object:
            kwargs["text"] = {"format": {"type": "json_object"}}
        if temperature is not None:
            kwargs["temperature"] = float(temperature)

        try:
            resp = self._client.responses.create(**kwargs)
        except Exception as exc:
            if "input" in str(exc).lower():
                fallback_input = (system_prompt or "") + "\n\n" + str(user_prompt)
                kwargs["input"] = fallback_input
                resp = self._client.responses.create(**kwargs)
            else:
                raise

        return LLMResponse(
            text=_responses_output_text(resp),
            model=str(model or self._default_model),
            usage=_safe_usage_from_responses(getattr(resp, "usage", None)),
        )
