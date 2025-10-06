"""
Chat API endpoint for Morpheus AGI Chatbot Framework.

This module provides the main chat functionality with LangChain integration.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from ..core.models import ChatRequest, ChatResponse, ErrorResponse
from ..core.llm import generate_chat_response, get_llm_health
from ..core.memory import store_conversation, get_memory_manager
from ..utils.logging import RequestLogger, LLMLogger
from ..utils.errors import handle_llm_error, log_error_context

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize loggers
request_logger = RequestLogger("chat")
llm_logger = LLMLogger()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint handles the core chat functionality using LangChain ChatOpenAI.
    It supports conversation history and project context (stubbed for V4).
    """
    try:
        # Log the incoming request
        request_logger.log_request(
            endpoint="/chat",
            method="POST",
            user_id=request.conversation_id
        )
        
        # Get conversation history if conversation_id is provided
        conversation_history = None
        if request.conversation_id:
            memory_manager = get_memory_manager()
            history = memory_manager.get_conversation_history(request.conversation_id, limit=10)
            conversation_history = [
                {"role": "user", "content": msg["user_message"]}
                for msg in history
            ] + [
                {"role": "assistant", "content": msg["ai_response"]}
                for msg in history
            ]
        
        # Log LLM request
        llm_logger.log_llm_request(
            model="gpt-5",  # Will be dynamic in future
            message_length=len(request.message),
            conversation_id=request.conversation_id
        )
        
        # Generate response using LangChain
        llm_response = generate_chat_response(
            message=request.message,
            conversation_history=conversation_history
        )
        
        # Check if LLM response was successful
        if not llm_response.get("success", False):
            raise Exception(llm_response.get("error", "Unknown LLM error"))
        
        # Log LLM response
        llm_logger.log_llm_response(
            model=llm_response.get("llm_model", "gpt-5"),
            response_length=len(llm_response["response"]),
            tokens_used=llm_response.get("tokens_used"),
            conversation_id=request.conversation_id
        )
        
        # Store conversation in memory if conversation_id is provided
        if request.conversation_id:
            store_conversation(
                conversation_id=request.conversation_id,
                message=request.message,
                response=llm_response["response"],
                metadata={
                    "project_id": request.project_id,
                    "llm_model": llm_response.get("llm_model"),
                    "tokens_used": llm_response.get("tokens_used")
                }
            )
        
        # Create response
        response = ChatResponse(
            response=llm_response["response"],
            conversation_id=request.conversation_id,
            llm_model=llm_response.get("llm_model"),
            tokens_used=llm_response.get("tokens_used")
        )
        
        # Log successful response
        request_logger.log_response(
            endpoint="/chat",
            status_code=200,
            response_time=0.0,  # Would be calculated in real implementation
            user_id=request.conversation_id
        )
        
        return response
        
    except Exception as e:
        # Log error
        request_logger.log_error(
            endpoint="/chat",
            error=e,
            user_id=request.conversation_id
        )
        
        # Log error context
        log_error_context(
            error=e,
            context={
                "endpoint": "/chat",
                "conversation_id": request.conversation_id,
                "project_id": request.project_id,
                "message_length": len(request.message)
            }
        )
        
        # Handle different types of errors
        if "llm" in str(e).lower() or "openai" in str(e).lower():
            raise handle_llm_error(e)
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": "Internal server error",
                    "error_code": "INTERNAL_ERROR"
                }
            )


@router.get("/chat/health")
async def chat_health() -> JSONResponse:
    """Health check for chat functionality."""
    try:
        # Check LLM health
        llm_health = get_llm_health()
        
        if llm_health["status"] == "healthy":
            return JSONResponse(
                status_code=200,
                content={
                    "status": "healthy",
                    "service": "chat",
                    "llm_status": llm_health["status"],
                    "model": llm_health.get("model", "unknown")
                }
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "service": "chat",
                    "llm_status": llm_health["status"],
                    "error": llm_health.get("error", "Unknown error")
                }
            )
            
    except Exception as e:
        logger.error(f"Chat health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "chat",
                "error": str(e)
            }
        )


@router.get("/chat/stats")
async def chat_stats() -> JSONResponse:
    """Get chat statistics."""
    try:
        memory_manager = get_memory_manager()
        stats = memory_manager.get_memory_stats()
        
        return JSONResponse(
            status_code=200,
            content={
                "conversations": stats["total_conversations"],
                "messages": stats["total_messages"],
                "memory_mode": stats["memory_mode"],
                "features": stats["features_available"]
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get chat stats: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to retrieve statistics",
                "details": str(e)
            }
        )
