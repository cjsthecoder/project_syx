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
        self._initialize_llm()
    
    def _initialize_llm(self) -> None:
        """Initialize the LangChain ChatOpenAI instance."""
        try:
            if not validate_openai_key():
                raise ValueError("OpenAI API key is not configured or invalid")
            
            model_config = get_model_config()
            
            self._llm = ChatOpenAI(
                openai_api_key=self.settings.openai_api_key,
                model_name=model_config["model_name"],
                temperature=model_config["temperature"],
                model_kwargs={"max_completion_tokens": model_config["max_tokens"]},
                streaming=False,  # Disable streaming for now
            )
            
            logger.info(f"LLM provider initialized with model: {model_config['model_name']}")
            
        except Exception as e:
            logger.error(f"Failed to initialize LLM provider: {str(e)}")
            raise
    
    def generate_response(
        self, 
        message: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None
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
            
            # Add system prompt if provided
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            
            # Add conversation history
            if conversation_history:
                for msg in conversation_history:
                    if msg.get("role") == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg.get("role") == "assistant":
                        messages.append(AIMessage(content=msg["content"]))
            
            # Add current user message
            messages.append(HumanMessage(content=message))
            
            # Generate response
            response = self._llm.invoke(messages)
            
            # Extract response content and metadata
            response_content = response.content if hasattr(response, 'content') else str(response)
            
            # Get token usage if available
            token_usage = getattr(response, 'usage_metadata', {})
            
            return {
                "response": response_content,
                "llm_model": self.settings.model_name,
                "tokens_used": token_usage.get("total_tokens", None),
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return {
                "response": f"I apologize, but I encountered an error: {str(e)}",
                "llm_model": self.settings.model_name,
                "tokens_used": None,
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
def generate_chat_response(message: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Generate a chat response using the global LLM provider."""
    provider = get_llm_provider()
    return provider.generate_response(message, conversation_history)


def get_llm_health() -> Dict[str, str]:
    """Get LLM provider health status."""
    provider = get_llm_provider()
    return provider.health_check()
