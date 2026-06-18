"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
LLM service layer for the Syx chatbot runtime.

Orchestration on top of the ``llm_model`` provider boundary: builds prompts,
records instrumentation, and exposes the high-level ``generate_chat_response`` /
``generate_text_response`` / ``generate_research_response`` /
``get_llm_health`` API consumed by the API and dream layers (factory-based, no
LangChain).
"""


import logging
import time
from typing import Any, Dict, List, Optional

from ..llm_model.base import LLMResponse
from ..llm_model.factory import get_llm_client
from ..llm_model.registry import get_active_llm_models
from ..tracking import get_instrumentation
from ..utils.tokens import count_tokens
from .config import get_settings, validate_openai_key

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate the token count of a text fragment.

    Args:
        text: Text to measure; treated as empty when falsy.

    Returns:
        The estimated number of tokens.
    """
    return int(count_tokens(text or ""))


def _build_messages(
    *,
    message: str,
    conversation_history: Optional[List[Dict[str, str]]],
    base_system_prompt: Optional[str],
    assistant_hint: Optional[str],
    rag_system_prompt: Optional[str],
) -> List[Dict[str, str]]:
    """Assemble the chat message list in canonical order.

    Order is base system prompt, assistant hint, RAG system prompt, prior
    conversation history (roles other than user/assistant/system are dropped),
    and finally the current user message.

    Args:
        message: Current user message placed last in the sequence.
        conversation_history: Prior turns to include; entries whose role is not
            user/assistant/system are skipped.
        base_system_prompt: Base system instructions prepended first.
        assistant_hint: Optional assistant-role priming message.
        rag_system_prompt: Optional retrieval context injected as a system
            message after the assistant hint.

    Returns:
        The ordered list of role/content message dicts ready for the LLM client.
    """
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
    """Runtime entry point for primary chat completions via the LLM factory."""

    def __init__(self) -> None:
        """Initialize the provider from settings.

        Raises:
            ValueError: If the OpenAI API key is missing or invalid.
        """
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
        """Generate a chat completion and record instrumentation.

        Args:
            message: The current user message.
            conversation_history: Prior turns to include before the user message.
            base_system_prompt: Base system instructions.
            assistant_hint: Optional assistant-role priming message.
            rag_system_prompt: Optional retrieval context injected as a system
                message.
            override_model: Model name overriding the configured default.
            temperature_override: Temperature overriding the configured default.
            completion_tokens_override: Max completion tokens override.
            instrument: Whether to record instrumentation for this call.

        Returns:
            A result dict with ``response`` text, model/usage fields, and a
            ``success`` flag. On failure the dict carries an apologetic
            ``response``, ``success`` False, and an ``error`` message rather
            than raising.
        """
        invocation_id = ""
        invoke_start = time.perf_counter()
        runtime_models = get_active_llm_models()
        used_model = str(override_model or runtime_models.main_model)

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
                                "\n".join(
                                    str((msg.get("content") or ""))
                                    for msg in (conversation_history or [])
                                )
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
                model=override_model or runtime_models.main_model,
                temperature=(
                    temperature_override
                    if temperature_override is not None
                    else self.settings.model_temperature
                ),
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
        """Return the active model configuration and API-key readiness.

        Returns:
            A dict with ``model_name``, ``temperature``, ``max_tokens``, and an
            ``api_key_configured`` boolean.
        """
        return {
            "model_name": get_active_llm_models().main_model,
            "temperature": self.settings.model_temperature,
            "max_tokens": self.settings.model_max_tokens,
            "api_key_configured": validate_openai_key(),
        }

    def health_check(self) -> Dict[str, str]:
        """Probe the LLM with a tiny request and report health status.

        Returns:
            A dict with ``status`` set to ``healthy`` (plus ``model``) on a
            successful probe, or ``unhealthy`` (plus ``error``) when the probe
            returns nothing or raises.
        """
        try:
            test = get_llm_client().generate_chat(
                messages=[{"role": "user", "content": "Hello"}],
                model=get_active_llm_models().main_model,
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
    """Return the process-wide ``LLMProvider``, creating it on first use.

    Returns:
        The cached ``LLMProvider`` singleton.
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider


def reset_llm_provider() -> None:
    """Clear the cached provider so the next access rebuilds it from settings."""
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
    """Generate a chat completion via the shared ``LLMProvider``.

    Args:
        message: The current user message.
        conversation_history: Prior turns to include before the user message.
        base_system_prompt: Base system instructions.
        assistant_hint: Optional assistant-role priming message.
        rag_system_prompt: Optional retrieval context injected as a system
            message.
        override_model: Model name overriding the configured default.
        temperature_override: Temperature overriding the configured default.
        instrument: Whether to record instrumentation for this call.

    Returns:
        The provider result dict (see ``LLMProvider.generate_response``).
    """
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


def _start_text_invocation(
    *,
    user_prompt: str,
    system_prompt: Optional[str],
    purpose: str,
    used_model: str,
    instrument: bool,
) -> str:
    """Record text prompt assembly and start an instrumentation invocation."""
    if not instrument:
        return ""

    instr = get_instrumentation()
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
    return instr.start_invocation(
        purpose=str(purpose or "main"),
        model=used_model,
        meta={"streaming": False, "api": "responses"},
    )


def _finish_text_invocation_success(
    *,
    invocation_id: str,
    response: LLMResponse,
    purpose: str,
    invoke_start: float,
) -> None:
    """Finalize a successful instrumented text invocation."""
    if not invocation_id:
        return

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
    get_instrumentation().end_invocation(
        invocation_id,
        usage=usage_payload,
        timing={"ttlt_ms": int((time.perf_counter() - invoke_start) * 1000.0)},
    )


def _finish_text_invocation_failure(
    *,
    invocation_id: str,
    purpose: str,
    used_model: str,
    invoke_start: float,
) -> None:
    """Finalize a failed instrumented text invocation with zeroed usage."""
    if not invocation_id:
        return

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


def _call_text_client(
    *,
    user_prompt: str,
    system_prompt: Optional[str],
    override_model: Optional[str],
    temperature_override: Optional[float],
    max_output_tokens: Optional[int],
    reasoning_effort: Optional[str],
    require_json_object: bool,
    research: bool,
) -> LLMResponse:
    """Dispatch to the standard or research-capable provider method."""
    runtime_models = get_active_llm_models()
    if research:
        return get_llm_client().generate_response_research(
            model=override_model or runtime_models.main_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature_override,
            max_output_tokens=max_output_tokens,
        )

    return get_llm_client().generate_response(
        model=override_model or runtime_models.main_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature_override,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        require_json_object=require_json_object,
    )


def _generate_text_response(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    require_json_object: bool = False,
    purpose: str = "main",
    instrument: bool = True,
    research: bool = False,
) -> LLMResponse:
    """Generate a text response through the shared LLM factory."""
    invocation_id = ""
    invoke_start = time.perf_counter()
    used_model = str(override_model or get_active_llm_models().main_model)

    try:
        invocation_id = _start_text_invocation(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            purpose=purpose,
            used_model=used_model,
            instrument=instrument,
        )
        response = _call_text_client(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            override_model=override_model,
            temperature_override=temperature_override,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            require_json_object=require_json_object,
            research=research,
        )

        _finish_text_invocation_success(
            invocation_id=invocation_id,
            response=response,
            purpose=purpose,
            invoke_start=invoke_start,
        )

        return response
    except Exception as exc:
        try:
            _finish_text_invocation_failure(
                invocation_id=invocation_id,
                purpose=purpose,
                used_model=used_model,
                invoke_start=invoke_start,
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


def generate_text_response(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    require_json_object: bool = False,
    purpose: str = "main",
    instrument: bool = True,
) -> LLMResponse:
    """Generate a non-chat text response through the shared LLM factory.

    Args:
        user_prompt: Primary user prompt text.
        system_prompt: Optional system instructions.
        override_model: Model name overriding the configured default.
        temperature_override: Temperature overriding the provider default.
        max_output_tokens: Maximum output tokens for the completion.
        reasoning_effort: Optional reasoning-effort hint passed to the client.
        require_json_object: Whether to constrain output to a JSON object.
        purpose: Instrumentation purpose label for this invocation.
        instrument: Whether to record instrumentation for this call.

    Returns:
        The raw ``LLMResponse`` from the factory client.

    Raises:
        Exception: Re-raised from the underlying client after instrumentation is
            finalized and the failure is logged.
    """
    return _generate_text_response(
        user_prompt,
        system_prompt=system_prompt,
        override_model=override_model,
        temperature_override=temperature_override,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        require_json_object=require_json_object,
        purpose=purpose,
        instrument=instrument,
    )


def generate_research_response(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    purpose: str = "main",
    instrument: bool = True,
) -> LLMResponse:
    """Generate a researched text response through the provider boundary.

    Args:
        user_prompt: Primary research prompt text.
        system_prompt: Optional system instructions.
        override_model: Model name overriding the configured default.
        temperature_override: Temperature overriding the provider default.
        max_output_tokens: Maximum output tokens for the completion.
        purpose: Instrumentation purpose label for this invocation.
        instrument: Whether to record instrumentation for this call.

    Returns:
        The raw ``LLMResponse`` from the factory client's research capability.

    Raises:
        Exception: Re-raised from the underlying client after instrumentation is
            finalized and the failure is logged.
    """
    return _generate_text_response(
        user_prompt,
        system_prompt=system_prompt,
        override_model=override_model,
        temperature_override=temperature_override,
        max_output_tokens=max_output_tokens,
        purpose=purpose,
        instrument=instrument,
        research=True,
    )


def get_llm_health() -> Dict[str, str]:
    """Return the health status of the shared ``LLMProvider``.

    Returns:
        The health-status dict from ``LLMProvider.health_check``.
    """
    return get_llm_provider().health_check()
