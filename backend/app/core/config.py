"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Configuration management for Morpheus AGI Chatbot Framework.

This module handles environment variable loading and configuration validation.
"""

import os
import logging
import math
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
    model_name: str = Field(default="gpt-5.2", description="OpenAI model name")
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
    log_max_bytes: int = Field(default=10 * 1024 * 1024, description="Max bytes per log file before rotation")
    log_backup_count: int = Field(default=5, description="Number of rotated log files to keep")
    log_preview_max_chars: int = Field(default=1024, gt=0, description="Max chars for log previews")
    
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
    max_embed_tokens_per_request: int = Field(
        default=250_000,
        gt=0,
        description="Max total tokens per embeddings API request (safety headroom under provider cap)",
    )

    # V2: Model list for selector
    available_models: list[str] = Field(
        default=[
            "gpt-5.2",
            "gpt-5.1",
            "gpt-5.1-mini",
            "gpt-5.1-nano",
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
    # DELTA-A.4.1: retrieval-stage limits are controlled by BASE_TOP_K + RETRIEVAL_MULTIPLIER (not route config).
    base_top_k: int = Field(default=5, gt=0, description="DELTA-A.4.1: base retrieval top-K (used to derive per-source K)")
    retrieval_multiplier: float = Field(default=2.0, gt=0.0, description="DELTA-A.4.1: per-source K multiplier (PER_SOURCE_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER))")
    rag_score_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Cosine similarity threshold (0..1) — temporary A.4.3-stage selection policy only")

    # V2.2: Chat history working memory
    chat_history_limit: int = Field(default=20, gt=0, description="Number of recent messages kept per project")

    # V2.3: Daily RAG bridge controls (global defaults)
    chat_history_limit_pairs: int = Field(default=10, gt=0, description="Number of recent prompt/response pairs kept in working memory")
    daily_rag_enabled: bool = Field(default=True, description="Enable daily RAG roll-off globally (per-project can override)")
    daily_rag_score_threshold: float = Field(default=0.70, ge=0.0, le=1.0, description="Similarity threshold for daily results — temporary A.4.3-stage selection policy only")
    daily_rag_weight: float = Field(default=1.2, gt=0.0, description="Weight multiplier applied to daily scores")

    # V2.3: Deduplication controls
    dedupe_exact: bool = Field(default=True, description="Enable exact-text deduplication across daily/main snippets")
    dedupe_near: bool = Field(default=True, description="Enable near-duplicate deduplication via cosine similarity")
    dedupe_similarity_threshold: float = Field(default=0.98, ge=0.0, le=1.0, description="Cosine threshold for near-duplicate detection")
    dedupe_keep_daily: bool = Field(default=True, description="Prefer keeping daily snippet on dedupe conflicts")

    # V2.3.1: Builder and reranking
    builder_model: str = Field(default="gpt-5-mini", description="LLM used for query builder/router")
    builder_confidence_min: float = Field(default=0.75, ge=0.0, le=1.0, description="Minimum confidence for full retrieval")
    builder_max_tokens: int = Field(default=1024, gt=0, description="Max tokens for builder output")
    builder_cache: bool = Field(default=True, description="Enable in-memory cache for builder JSON")
    topic_boost: float = Field(default=1.10, gt=0.0, description="Multiplicative boost for topic overlap")
    decision_boost: float = Field(default=1.05, gt=0.0, description="Multiplicative boost for decision overlap")
    question_boost: float = Field(default=1.02, gt=0.0, description="Multiplicative boost for open-question overlap")

    # V2.6: Defaults and file paths
    default_system_prompt_path: str = Field(
        default="backend/app/config/defaults/system_prompt.txt",
        description="Path to the default system prompt file"
    )
    default_personality_prompt_path: str = Field(
        default="backend/app/config/defaults/personality.json",
        description="Path to the default personality JSON file"
    )
    # V2.6: Size caps
    system_prompt_max_bytes: int = Field(default=64 * 1024, gt=0, description="Max size of system_prompt.txt in bytes")
    personality_max_bytes: int = Field(default=8 * 1024, gt=0, description="Max size of personality.json in bytes")
    payload_max_bytes: int = Field(default=128 * 1024, gt=0, description="Max size of combined request payload in bytes")

    # V3.1: Sleep scheduler
    enable_scheduler: bool = Field(default=True, description="Enable sleep cycle scheduler (daily)")
    sleep_cycle_hour: int = Field(default=3, ge=0, le=23, description="Local hour (0-23) to run sleep cycle")
    sleep_cycle_minute: int = Field(default=0, ge=0, le=59, description="Local minute (0-59) to run sleep cycle")
    verify_rag: bool = Field(default=True, description="V3.3: enable post-rebuild verification step")
    force_rag_rebuild_on_startup: bool = Field(
        default=False,
        description="Force rebuilding all project FAISS indexes during server startup",
    )
    # V3.5: Streaming
    streaming_enabled: bool = Field(default=True, description="Enable streaming chat endpoint")
    stream_flush_ms: int = Field(default=50, gt=0, description="Flush cadence for streaming chunks in milliseconds")
    stream_timeout_ms: int = Field(default=60000, gt=0, description="Overall stream timeout in milliseconds")
    # V4.1: Dream orchestrator
    enable_dream: bool = Field(default=True, description="Enable Dream orchestrator")
    max_workers: int = Field(default=1, description="Dream executor worker count (MAX_WORKERS)")
    # V4.1.2: Dream agent configuration
    dream_model: str = Field(default="gpt-5.2", description="Dream LLM model")
    dream_temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Dream LLM temperature")
    dream_max_tokens: int = Field(default=32000, gt=0, description="Max tokens for Dream LLM completion")
    dream_enable_remote_research: bool = Field(default=True, description="Enable OpenAI web_search for Dream")
    dream_remote_context_max_tokens: int = Field(default=32000, gt=0, description="Max tokens for remote context inclusion")
    dream_topic_boost: float = Field(default=1.5, gt=0.0, description="Namespace boost used for topic hinting in RAG")
    # V4.1.3.1: Debug file generation
    generate_debug_files: bool = Field(default=False, description="V4.1.3.1: Enable writing debug files (e.g., debug_context.txt)")

# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings


def compute_per_source_k(base_top_k: int, retrieval_multiplier: float) -> int:
    """
    DELTA-A.4.1:
      PER_SOURCE_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER)
    """
    try:
        k = int(math.ceil(float(base_top_k) * float(retrieval_multiplier)))
    except Exception:
        # Best-effort fallback: if multiplier is invalid, treat it as 1.0 by
        # returning BASE_TOP_K (clamped to non-negative).
        try:
            return max(0, int(base_top_k))
        except Exception:
            return 0

    # Allow 0 to represent "skip retrieval" (e.g., multiplier=0 or base_top_k=0).
    return max(0, k)


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
