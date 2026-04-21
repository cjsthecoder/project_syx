"""
OpenAI-backed implementations for chat + responses APIs.
"""


import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openai import OpenAI

from ..base import LLMResponse, LLMUsage, Message

logger = logging.getLogger(__name__)


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        dumped = getattr(value, "model_dump", None)
        if callable(dumped):
            obj = dumped(mode="python")
            if isinstance(obj, dict):
                return obj
    except Exception as exc:
        logger.debug("openai_provider model_dump parse skipped detail=%s", exc)
    return {}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default)


def _extract_text_parts(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
                continue
            md = _as_mapping(item)
            text = md.get("text")
            if isinstance(text, str) and text:
                out.append(text)
                continue
            if isinstance(text, dict):
                nested = text.get("value")
                if isinstance(nested, str) and nested:
                    out.append(nested)
                    continue
            if md.get("type") == "output_text":
                maybe = md.get("text")
                if isinstance(maybe, str) and maybe:
                    out.append(maybe)
        return "".join(out)
    return ""


def _safe_usage_from_chat(usage: Any) -> LLMUsage:
    try:
        usage_map = _as_mapping(usage)
        prompt = _coerce_int(getattr(usage, "prompt_tokens", None), _coerce_int(usage_map.get("prompt_tokens", 0)))
        completion = _coerce_int(
            getattr(usage, "completion_tokens", None),
            _coerce_int(usage_map.get("completion_tokens", 0)),
        )
        # SDK 2.x can surface input/output naming in some envelopes.
        if prompt <= 0:
            prompt = _coerce_int(getattr(usage, "input_tokens", None), _coerce_int(usage_map.get("input_tokens", 0)))
        if completion <= 0:
            completion = _coerce_int(
                getattr(usage, "output_tokens", None),
                _coerce_int(usage_map.get("output_tokens", 0)),
            )
        total = _coerce_int(
            getattr(usage, "total_tokens", None),
            _coerce_int(usage_map.get("total_tokens", prompt + completion)),
        )
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
        usage_map = _as_mapping(usage)
        prompt = _coerce_int(getattr(usage, "input_tokens", None), _coerce_int(usage_map.get("input_tokens", 0)))
        completion = _coerce_int(getattr(usage, "output_tokens", None), _coerce_int(usage_map.get("output_tokens", 0)))
        total = _coerce_int(
            getattr(usage, "total_tokens", None),
            _coerce_int(usage_map.get("total_tokens", prompt + completion)),
        )
        extra: Dict[str, Any] = {}
        for k in ("input_token_details", "output_token_details", "reasoning_tokens", "cached_tokens"):
            try:
                v = getattr(usage, k, None)
                if v is None:
                    v = usage_map.get(k)
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
        parsed = _extract_text_parts(output_text)
        if parsed:
            return parsed
    except Exception as exc:
        logger.warning("openai_provider failed reading output_text detail=%s", exc)
    out: List[str] = []
    try:
        items = getattr(resp, "output", None)
        if items is None:
            items = _as_mapping(resp).get("output", [])
        for item in items or []:
            item_type = getattr(item, "type", None)
            if not item_type:
                item_type = _as_mapping(item).get("type")
            if item_type != "message":
                continue
            content = getattr(item, "content", None)
            if content is None:
                content = _as_mapping(item).get("content", [])
            for c in content or []:
                c_type = getattr(c, "type", None)
                if not c_type:
                    c_type = _as_mapping(c).get("type")
                if c_type != "output_text":
                    continue
                text = getattr(c, "text", None)
                if text is None:
                    text = _as_mapping(c).get("text")
                parsed = _extract_text_parts(text)
                if parsed:
                    out.append(parsed)
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
                content = getattr(msg, "content", None)
                if content is None:
                    content = _as_mapping(msg).get("content")
                text = _extract_text_parts(content).strip()
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
                # Preserve exact whitespace/newlines in streaming chunks.
                parsed = _extract_text_parts(piece)
                if parsed != "":
                    yield parsed, None
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
            detail = str(exc).lower()
            if "input" in detail:
                fallback_input = (system_prompt or "") + "\n\n" + str(user_prompt)
                kwargs["input"] = fallback_input
                resp = self._client.responses.create(**kwargs)
            elif "text" in detail and require_json_object:
                # SDK compatibility fallback when text.format contract changes.
                kwargs.pop("text", None)
                resp = self._client.responses.create(**kwargs)
            else:
                raise

        return LLMResponse(
            text=_responses_output_text(resp),
            model=str(model or self._default_model),
            usage=_safe_usage_from_responses(getattr(resp, "usage", None)),
        )
