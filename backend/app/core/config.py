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


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = {
        "protected_namespaces": ("settings_",),
        "env_file": ".env",
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
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")
    
    # CORS Configuration
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="Allowed CORS origins"
    )
    
    # Future Configuration (V2-V4)
    # RAG Configuration (V2)
    # rag_index_path: str = Field(default="./data/rag_index", description="RAG index path")
    # rag_chunk_size: int = Field(default=1000, description="RAG chunk size")
    # rag_chunk_overlap: int = Field(default=200, description="RAG chunk overlap")
    
    # Memory Configuration (V3)
    # memory_retention_days: int = Field(default=30, description="Memory retention in days")
    # memory_cleanup_hour: int = Field(default=2, ge=0, le=23, description="Cleanup hour (0-23)")
    
    # Project Configuration (V4)
    # default_project_id: str = Field(default="default", description="Default project ID")
    # max_projects: int = Field(default=10, gt=0, description="Maximum number of projects")
    


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
