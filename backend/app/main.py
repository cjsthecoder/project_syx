"""
Morpheus AGI Chatbot Framework - FastAPI Main Entry Point

This is the main FastAPI application that provides the backend API for the Morpheus chatbot.
It includes endpoints for chat, RAG queries, projects, and sleep cycle management.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Morpheus AGI Chatbot API",
    description="Backend API for the Morpheus chatbot framework",
    version="1.0.0"
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request/response
class ChatRequest(BaseModel):
    message: str
    project_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

class RAGRequest(BaseModel):
    query: str
    project_id: Optional[str] = None

class RAGResponse(BaseModel):
    response: str

class ProjectRequest(BaseModel):
    project_id: Optional[str] = None

class ProjectResponse(BaseModel):
    response: str

class SleepCycleRequest(BaseModel):
    project_id: Optional[str] = None

class SleepCycleResponse(BaseModel):
    response: str

# Health check endpoint
@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Morpheus AGI Chatbot API is running"}

@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "service": "morpheus-api",
        "version": "1.0.0"
    }

# Chat endpoint - Main conversation interface
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint for user-AI conversation.
    
    This endpoint will be connected to LangChain ChatOpenAI in the next implementation phase.
    Currently returns a placeholder response.
    """
    try:
        logger.info(f"Chat request received: {request.message[:50]}...")
        
        # TODO: Integrate with LangChain ChatOpenAI
        # For now, return a placeholder response
        response_text = f"Chat functionality not yet implemented. You said: '{request.message}'"
        
        return ChatResponse(response=response_text)
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# RAG query endpoint - Stubbed for future implementation
@app.post("/query_rag", response_model=RAGResponse)
async def query_rag(request: RAGRequest):
    """
    RAG (Retrieval-Augmented Generation) query endpoint.
    
    This endpoint is stubbed for future FAISS integration in Version 2.
    Currently returns a placeholder response.
    """
    try:
        logger.info(f"RAG query received: {request.query[:50]}...")
        
        # TODO: Implement FAISS-based RAG in Version 2
        response_text = "RAG not implemented. This feature will be available in Version 2."
        
        return RAGResponse(response=response_text)
        
    except Exception as e:
        logger.error(f"Error in RAG endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Projects endpoint - Stubbed for future multi-project support
@app.get("/projects", response_model=ProjectResponse)
async def get_projects():
    """
    Get list of available projects.
    
    This endpoint is stubbed for future multi-project memory management in Version 4.
    Currently returns a placeholder response.
    """
    try:
        logger.info("Projects list requested")
        
        # TODO: Implement project management in Version 4
        response_text = "Project management not implemented. This feature will be available in Version 4."
        
        return ProjectResponse(response=response_text)
        
    except Exception as e:
        logger.error(f"Error in projects endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/projects", response_model=ProjectResponse)
async def switch_project(request: ProjectRequest):
    """
    Switch to a different project context.
    
    This endpoint is stubbed for future multi-project memory management in Version 4.
    Currently returns a placeholder response.
    """
    try:
        logger.info(f"Project switch requested: {request.project_id}")
        
        # TODO: Implement project switching in Version 4
        response_text = f"Project switching not implemented. Requested project: {request.project_id or 'default'}"
        
        return ProjectResponse(response=response_text)
        
    except Exception as e:
        logger.error(f"Error in project switch endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Sleep cycle endpoint - Stubbed for future memory pruning
@app.post("/sleep_cycle", response_model=SleepCycleResponse)
async def trigger_sleep_cycle(request: SleepCycleRequest):
    """
    Trigger memory pruning and sleep cycle.
    
    This endpoint is stubbed for future nightly pruning in Version 3.
    Currently returns a placeholder response.
    """
    try:
        logger.info(f"Sleep cycle triggered for project: {request.project_id}")
        
        # TODO: Implement memory pruning in Version 3
        response_text = "Sleep cycle not implemented. This feature will be available in Version 3."
        
        return SleepCycleResponse(response=response_text)
        
    except Exception as e:
        logger.error(f"Error in sleep cycle endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    
    # Get configuration from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"
    
    logger.info(f"Starting Morpheus API server on {host}:{port}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
