"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
LLM integration for Syx chatbot runtime (factory-based, no LangChain).
"""


import logging
import time
from typing import Any, Dict, List, Optional

from .config import get_settings, validate_openai_key
from ..llm_model.base import LLMResponse
from ..llm_model.factory import get_llm_client
from ..tracking import get_instrumentation
from ..utils.tokens import count_tokens

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    return int(count_tokens(text or ""))


def _build_messages(
    *,
    message: str,
    conversation_history: Optional[List[Dict[str, str]]],
    base_system_prompt: Optional[str],
    assistant_hint: Optional[str],
    rag_system_prompt: Optional[str],
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if base_system_prompt:
        messages.append({"role": "system", "content": base_system_prompt})
    if assistant_hint:
        messages.append({"role": "assistant", "content": assistant_hint})
    if rag_system_prompt:
        messages.append({"role": "system", "content": rag_system_prompt})
    if conversation_history:
        for item in conversation_history:
            role = str(item.get("role") or "").lower()
            if role not in {"user", "assistant", "system"}:
                continue
            messages.append({"role": role, "content": str(item.get("content") or "")})
    messages.append({"role": "user", "content": str(message or "")})
    return messages


class LLMProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not validate_openai_key():
            raise ValueError("OpenAI API key is not configured or invalid")

    def generate_response(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        base_system_prompt: Optional[str] = None,
        assistant_hint: Optional[str] = None,
        rag_system_prompt: Optional[str] = None,
        override_model: Optional[str] = None,
        temperature_override: Optional[float] = None,
        completion_tokens_override: Optional[int] = None,
        instrument: bool = True,
    ) -> Dict[str, Any]:
        invocation_id = ""
        invoke_start = time.perf_counter()
        used_model = str(override_model or self.settings.model_name)

        try:
            messages = _build_messages(
                message=message,
                conversation_history=conversation_history,
                base_system_prompt=base_system_prompt,
                assistant_hint=assistant_hint,
                rag_system_prompt=rag_system_prompt,
            )
            instr = get_instrumentation()
            if instrument:
                instr.record_stage(
                    "prompt_assembly",
                    {
                        "module": "llm",
                        "prompt_system_tokens_est": int(_estimate_tokens(base_system_prompt or "")),
                        "prompt_history_tokens_est": int(
                            _estimate_tokens(
                                "\n".join(str((msg.get("content") or "")) for msg in (conversation_history or []))
                            )
                        ),
                        "prompt_rag_tokens_est": int(_estimate_tokens(rag_system_prompt or "")),
                        "prompt_profile_tokens_est": int(_estimate_tokens(assistant_hint or "")),
                        "prompt_other_tokens_est": int(_estimate_tokens(message or "")),
                        "message_count": int(len(messages)),
                    },
                )
                invocation_id = instr.start_invocation(
                    purpose="main",
                    model=used_model,
                    meta={"streaming": False},
                )

            response = get_llm_client().generate_chat(
                messages=messages,
                model=override_model or self.settings.model_name,
                temperature=temperature_override if temperature_override is not None else self.settings.model_temperature,
                max_completion_tokens=(
                    int(completion_tokens_override)
                    if completion_tokens_override is not None
                    else int(self.settings.model_max_tokens)
                ),
            )

            if instrument and invocation_id:
                usage_payload = {
                    "purpose": "main",
                    "model": response.model,
                    "prompt_tokens_reported": int(response.usage.prompt_tokens_reported),
                    "completion_tokens_reported": int(response.usage.completion_tokens_reported),
                    "total_tokens_reported": int(response.usage.total_tokens_reported),
                    "usage_is_estimate": bool(response.usage.usage_is_estimate),
                }
                if response.usage.extra_usage:
                    usage_payload["extra_usage"] = response.usage.extra_usage
                instr.end_invocation(
                    invocation_id,
                    usage=usage_payload,
                    timing={"ttlt_ms": int((time.perf_counter() - invoke_start) * 1000.0)},
                )

            return {
                "response": response.text,
                "llm_model": response.model,
                "tokens_used": int(response.usage.total_tokens_reported),
                "input_tokens": int(response.usage.prompt_tokens_reported),
                "output_tokens": int(response.usage.completion_tokens_reported),
                "success": True,
            }
        except Exception as exc:
            try:
                if instrument and invocation_id:
                    get_instrumentation().end_invocation(
                        invocation_id,
                        usage={
                            "purpose": "main",
                            "model": used_model,
                            "prompt_tokens_reported": 0,
                            "completion_tokens_reported": 0,
                            "total_tokens_reported": 0,
                            "usage_is_estimate": True,
                        },
                        timing={"ttlt_ms": int((time.perf_counter() - invoke_start) * 1000.0)},
                    )
            except Exception as finalize_exc:
                logger.warning(
                    "llm.generate_response failed ending invocation invocation_id=%s detail=%s",
                    invocation_id,
                    finalize_exc,
                )
            logger.error("Error generating response: %s", exc)
            return {
                "response": f"I apologize, but I encountered an error: {str(exc)}",
                "llm_model": used_model,
                "tokens_used": None,
                "input_tokens": None,
                "output_tokens": None,
                "success": False,
                "error": str(exc),
            }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.settings.model_name,
            "temperature": self.settings.model_temperature,
            "max_tokens": self.settings.model_max_tokens,
            "api_key_configured": validate_openai_key(),
        }

    def health_check(self) -> Dict[str, str]:
        try:
            test = get_llm_client().generate_chat(
                messages=[{"role": "user", "content": "Hello"}],
                model=self.settings.model_name,
                temperature=1.0,
                max_completion_tokens=32,
            )
            if test.text is not None:
                return {"status": "healthy", "model": str(test.model)}
            return {"status": "unhealthy", "error": "No response from model"}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}


_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider


def reset_llm_provider() -> None:
    global _llm_provider
    _llm_provider = None


def generate_chat_response(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    base_system_prompt: Optional[str] = None,
    assistant_hint: Optional[str] = None,
    rag_system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
    instrument: bool = True,
) -> Dict[str, Any]:
    provider = get_llm_provider()
    return provider.generate_response(
        message=message,
        conversation_history=conversation_history,
        base_system_prompt=base_system_prompt,
        assistant_hint=assistant_hint,
        rag_system_prompt=rag_system_prompt,
        override_model=override_model,
        temperature_override=temperature_override,
        instrument=instrument,
    )


def generate_text_response(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    require_json_object: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    purpose: str = "main",
    instrument: bool = True,
) -> LLMResponse:
    """Generate a non-chat text response through the shared LLM factory."""
    settings = get_settings()
    invocation_id = ""
    invoke_start = time.perf_counter()
    used_model = str(override_model or settings.model_name)

    try:
        instr = get_instrumentation()
        if instrument:
            instr.record_stage(
                "prompt_assembly",
                {
                    "module": "llm",
                    "purpose": str(purpose or "main"),
                    "prompt_system_tokens_est": int(_estimate_tokens(system_prompt or "")),
                    "prompt_other_tokens_est": int(_estimate_tokens(user_prompt or "")),
                    "message_count": 1 + (1 if system_prompt else 0),
                },
            )
            invocation_id = instr.start_invocation(
                purpose=str(purpose or "main"),
                model=used_model,
                meta={"streaming": False, "api": "responses"},
            )

        response = get_llm_client().generate_response(
            model=override_model or settings.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature_override,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            require_json_object=require_json_object,
            tools=tools,
        )

        if instrument and invocation_id:
            usage_payload = {
                "purpose": str(purpose or "main"),
                "model": response.model,
                "prompt_tokens_reported": int(response.usage.prompt_tokens_reported),
                "completion_tokens_reported": int(response.usage.completion_tokens_reported),
                "total_tokens_reported": int(response.usage.total_tokens_reported),
                "usage_is_estimate": bool(response.usage.usage_is_estimate),
            }
            if response.usage.extra_usage:
                usage_payload["extra_usage"] = response.usage.extra_usage
            instr.end_invocation(
                invocation_id,
                usage=usage_payload,
                timing={"ttlt_ms": int((time.perf_counter() - invoke_start) * 1000.0)},
            )

        return response
    except Exception as exc:
        try:
            if instrument and invocation_id:
                get_instrumentation().end_invocation(
                    invocation_id,
                    usage={
                        "purpose": str(purpose or "main"),
                        "model": used_model,
                        "prompt_tokens_reported": 0,
                        "completion_tokens_reported": 0,
                        "total_tokens_reported": 0,
                        "usage_is_estimate": True,
                    },
                    timing={"ttlt_ms": int((time.perf_counter() - invoke_start) * 1000.0)},
                )
        except Exception as finalize_exc:
            logger.warning(
                "llm.generate_text_response failed ending invocation invocation_id=%s detail=%s",
                invocation_id,
                finalize_exc,
            )
        logger.error(
            "Error generating text response purpose=%s model=%s: %s",
            str(purpose or "main"),
            used_model,
            exc,
        )
        raise


def get_llm_health() -> Dict[str, str]:
    return get_llm_provider().health_check()
