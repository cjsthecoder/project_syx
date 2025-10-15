"""
Configuration management for Morpheus AGI Chatbot Framework.

This module handles environment variable loading and configuration validation.
"""

import os
import logging
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings

# Set up module-level logger
logger = logging.getLogger(__name__)

# Resolve repository root .env path regardless of CWD
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_ENV_FILE = os.path.join(_REPO_ROOT, ".env")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = {
        "protected_namespaces": ("settings_",),
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }
    
    # OpenAI Configuration
    openai_api_key: str = Field(..., description="OpenAI API key (required)")
    model_name: str = Field(default="gpt-5", description="OpenAI model name")
    model_temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Model temperature")
    model_max_tokens: int = Field(default=32000, gt=0, description="Maximum tokens per response")
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, gt=0, le=65535, description="Server port")
    reload: bool = Field(default=True, description="Enable auto-reload in development")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", description="Global logging level (legacy)")
    log_format: str = Field(default="json", description="Log format (json or text)")
    log_level_console: str = Field(default="INFO", description="Console log level")
    log_level_file: str = Field(default="DEBUG", description="File log level")
    
    # CORS Configuration
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="Allowed CORS origins"
    )

    # V2: Database & Storage
    db_path: str = Field(default="backend/app/data/morpheus.db", description="SQLite DB path")
    max_upload_mb: int = Field(default=10, gt=0, description="Max upload size per file (MB)")
    max_batch_mb: int = Field(default=50, gt=0, description="Max total batch size (MB)")
    storage_limit_mb: int = Field(default=500, gt=0, description="Total storage limit per project (MB)")

    # V2: Embeddings / RAG
    embedding_model: str = Field(default="text-embedding-3-large", description="OpenAI embedding model")
    chunk_size: int = Field(default=800, gt=0, description="Chunk size for embeddings")
    chunk_overlap: int = Field(default=100, ge=0, description="Chunk overlap for embeddings")

    # V2: Model list for selector
    available_models: list[str] = Field(
        default=[
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
        ],
        description="Whitelisted chat models",
    )
    
    # V2.1: RAG-on-chat controls
    rag_on_chat: bool = Field(default=True, description="Enable retrieval injection during chat")
    rag_top_k: int = Field(default=5, gt=0, description="Top-K retrieved chunks")
    rag_snippet_max_tokens: int = Field(default=500, gt=0, description="Max tokens per snippet")
    rag_context_max_tokens: int = Field(default=5000, gt=100, description="Max tokens for entire context block")
    rag_score_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Cosine similarity threshold (0..1)")

    # V2.2: Chat history working memory
    chat_history_limit: int = Field(default=20, gt=0, description="Number of recent messages kept per project")


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings


def validate_openai_key() -> bool:
    """Validate that OpenAI API key is set and not empty."""
    return bool(settings.openai_api_key and settings.openai_api_key != "your-openai-api-key-here")


def get_model_config() -> dict:
    """Get model configuration for LangChain."""
    return {
        "model_name": settings.model_name,
        "temperature": settings.model_temperature,
        "max_tokens": settings.model_max_tokens,
    }
