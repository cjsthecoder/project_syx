"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

"""
LangChain integration for Morpheus AGI Chatbot Framework.

This module provides the LLM abstraction layer using LangChain ChatOpenAI.
"""

import logging
from typing import Optional, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage

from .config import get_settings, validate_openai_key, get_model_config

# Set up module-level logger
logger = logging.getLogger(__name__)


class LLMProvider:
    """LangChain-based LLM provider for OpenAI integration."""
    
    def __init__(self):
        """Initialize the LLM provider."""
        self.settings = get_settings()
        self._llm: Optional[ChatOpenAI] = None
        # Cache of models that do not support non-default temperature
        self._temp_unsupported: set[str] = set()
        self._initialize_llm()
    
    def _initialize_llm(self) -> None:
        """Initialize the LangChain ChatOpenAI instance."""
        try:
            if not validate_openai_key():
                raise ValueError("OpenAI API key is not configured or invalid")
            
            model_config = get_model_config()
            
            self._llm = ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=model_config["model_name"],
                temperature=1.0,
                model_kwargs={"max_completion_tokens": model_config["max_tokens"]},
                streaming=False,
            )
            
            logger.info(f"LLM provider initialized with model: {model_config['model_name']}")
            
        except Exception as e:
            logger.error(f"Failed to initialize LLM provider: {str(e)}")
            raise
    
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
    ) -> Dict[str, Any]:
        """
        Generate a response using the LLM.
        
        Args:
            message: User message
            conversation_history: Previous conversation messages
            system_prompt: System prompt for the AI
            
        Returns:
            Dictionary containing response and metadata
        """
        try:
            if not self._llm:
                raise ValueError("LLM provider not initialized")
            
            # Build message history
            messages = []
            
            # V2.6: Add base project system prompt first
            if base_system_prompt:
                messages.append(SystemMessage(content=base_system_prompt))
            # V2.6: Add assistant personality hint
            if assistant_hint:
                messages.append(AIMessage(content=assistant_hint))
            # V2.6: Add RAG merged context as system message (after hint, before user)
            if rag_system_prompt:
                messages.append(SystemMessage(content=rag_system_prompt))
            
            # Add conversation history
            if conversation_history:
                for msg in conversation_history:
                    if msg.get("role") == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg.get("role") == "assistant":
                        messages.append(AIMessage(content=msg["content"]))
            
            # Add current user message
            messages.append(HumanMessage(content=message))

            # Debug: show roles and content lengths of messages being sent
            try:
                roles = [getattr(m, "type", m.__class__.__name__) for m in messages]
                lens = [len(getattr(m, "content", "") or "") for m in messages]
                logger.debug("[PROMPT] sending messages roles=%s lens=%s", roles, lens)
            except Exception:
                pass
            
            # Determine temperature
            temp_value = (
                float(temperature_override)
                if temperature_override is not None
                else self.settings.model_temperature
            )
            # Optionally use an override model for this call with temperature fallback + model capability cache
            def _invoke_with(model_name: str, temperature: float):
                llm = ChatOpenAI(
                    api_key=self.settings.openai_api_key,
                    model=model_name,
                    temperature=temperature,
                    model_kwargs={
                        "max_completion_tokens": (
                            int(completion_tokens_override)
                            if completion_tokens_override is not None
                            else self.settings.model_max_tokens
                        )
                    },
                    streaming=False,
                 )
                return llm.invoke(messages)

            used_model = self.settings.model_name
            model_to_use = override_model or self.settings.model_name
            # Decide effective temperature based on cache (skip override if unsupported for this model)
            if model_to_use in self._temp_unsupported:
                effective_temp = self.settings.model_temperature
            else:
                effective_temp = (
                    float(temperature_override)
                    if temperature_override is not None
                    else self.settings.model_temperature
                )
            try:
                if override_model and override_model != self.settings.model_name:
                    used_model = override_model
                    response = _invoke_with(override_model, effective_temp)
                else:
                    if effective_temp != self.settings.model_temperature:
                        response = _invoke_with(self.settings.model_name, effective_temp)
                    else:
                        response = self._llm.invoke(messages)
            except Exception as e:
                # Fallback: retry with default temperature if temperature override is not supported
                msg = str(e).lower()
                if "temperature" in msg or "unsupported_value" in msg or "invalid_request_error" in msg:
                    # Remember that this model doesn't support non-default temperature
                    first_time = model_to_use not in self._temp_unsupported
                    self._temp_unsupported.add(model_to_use)
                    if first_time:
                        logger.info("LLM model %s does not support temperature; using default thereafter", model_to_use)
                    # Retry once with default temperature, silently on subsequent calls
                    if override_model and override_model != self.settings.model_name:
                        response = _invoke_with(override_model, 1.0)
                        used_model = override_model
                    else:
                        response = _invoke_with(self.settings.model_name, 1.0)
                        used_model = self.settings.model_name
                else:
                    raise
            
            # Extract response content and metadata
            response_content = getattr(response, "content", str(response)) or ""
            # Get token usage if available (LangChain 0.2.x)
            meta = getattr(response, "response_metadata", {}) or {}
            token_usage = meta.get("token_usage", {}) or {}
            input_tok = token_usage.get("prompt_tokens") or token_usage.get("input_tokens")
            output_tok = token_usage.get("completion_tokens") or token_usage.get("output_tokens")
            total_tok = token_usage.get("total_tokens")
            
            return {
                "response": response_content,
                "llm_model": used_model,
                "tokens_used": total_tok,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return {
                "response": f"I apologize, but I encountered an error: {str(e)}",
                "llm_model": self.settings.model_name,
                "tokens_used": None,
                "input_tokens": None,
                "output_tokens": None,
                "success": False,
                "error": str(e)
            }
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model configuration."""
        return {
            "model_name": self.settings.model_name,
            "temperature": self.settings.model_temperature,
            "max_tokens": self.settings.model_max_tokens,
            "api_key_configured": validate_openai_key()
        }
    
    def health_check(self) -> Dict[str, str]:
        """Check if the LLM provider is healthy."""
        try:
            if not self._llm:
                return {"status": "unhealthy", "error": "LLM not initialized"}
            
            # Test with a simple message
            test_response = self._llm.invoke([HumanMessage(content="Hello")])
            
            if test_response:
                return {"status": "healthy", "model": self.settings.model_name}
            else:
                return {"status": "unhealthy", "error": "No response from model"}
                
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# Global LLM provider instance
_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """Get the global LLM provider instance."""
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider


def reset_llm_provider() -> None:
    """Reset the global LLM provider instance."""
    global _llm_provider
    _llm_provider = None


# Convenience functions

def generate_chat_response(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    base_system_prompt: Optional[str] = None,
    assistant_hint: Optional[str] = None,
    rag_system_prompt: Optional[str] = None,
    override_model: Optional[str] = None,
    temperature_override: Optional[float] = None,
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
    )


def get_llm_health() -> Dict[str, str]:
    provider = get_llm_provider()
    return provider.health_check()
