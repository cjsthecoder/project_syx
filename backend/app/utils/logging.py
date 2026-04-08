"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Enhanced logging configuration for Morpheus AGI Chatbot Framework.

This module provides structured logging with colored console output and timestamped files.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import contextvars
from datetime import datetime
from typing import Optional

# Import ctypes for Windows color support
try:  # pragma: no cover - import success/failure is environment-dependent
    import ctypes  # pragma: no cover
except ImportError:  # pragma: no cover
    ctypes = None  # pragma: no cover

from ..core.config import get_settings


class CustomFormatter(logging.Formatter):  # pylint: disable=R0903
    """Custom formatter for colored console output with cross-platform support."""
    # pylint: disable=C0301

    def __init__(self):
        super().__init__()
        # Check if terminal supports colors
        self.use_colors = self._supports_colors()

        if self.use_colors:
            self.formats = {
                logging.DEBUG: '\033[90m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m',
                logging.INFO: '\033[92m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m',
                logging.WARNING: '\033[93m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m',
                logging.ERROR: '\033[91m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m',
                logging.CRITICAL: '\033[95m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m',
            }
        else:
            # Fallback to plain text format
            self.formats = {
                logging.DEBUG: '%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s',
                logging.INFO: '%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s',
                logging.WARNING: '%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s',
                logging.ERROR: '%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s',
                logging.CRITICAL: '%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s',
            }

    def _supports_colors(self):
        """Check if the terminal supports ANSI color codes."""
        # Check if we're in a terminal
        if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
            return False

        # Check for common terminal types that support colors
        term = os.environ.get('TERM', '')
        if term in ('xterm', 'xterm-256color', 'linux', 'screen', 'screen-256color'):
            return True

        # Check for Windows 10+ with ANSI support
        if os.name == 'nt' and ctypes:
            try:
                kernel32 = ctypes.windll.kernel32
                return kernel32.GetConsoleMode(kernel32.GetStdHandle(-11)) & 0x0004  # pragma: no cover - Windows-specific API call
            except AttributeError:
                return False

        return False

    def format(self, record):
        log_fmt = self.formats.get(record.levelno, self.formats[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)



def setup_logging() -> None:
    """Set up application logging configuration with colored console and timestamped files."""
    
    settings = get_settings()
    # Legacy global level (retained for component loggers default)
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    # New per-handler levels
    console_level = getattr(logging, settings.log_level_console.upper(), logging.INFO)
    file_level = getattr(logging, settings.log_level_file.upper(), logging.DEBUG)
    
    # Create logs directory
    script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logs_dir = os.path.join(script_dir, 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    # Create timestamped log filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = os.path.join(logs_dir, f'syx_{timestamp}.log')
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    
    # Create rotating file handler (DEBUG level for detailed logs)
    file_handler = RotatingFileHandler(
        log_filename,
        maxBytes=int(settings.log_max_bytes),
        backupCount=int(settings.log_backup_count)
    )
    file_handler.setLevel(file_level)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s:%(funcName)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Create console handler with custom formatter honoring LOG_LEVEL
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(CustomFormatter())
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Configure specific loggers to reduce noise and use our formatter
    if console_level == logging.DEBUG or log_level == logging.DEBUG:
        logging.getLogger("uvicorn").setLevel(logging.DEBUG)
        logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)
        logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)
        logging.getLogger("fastapi").setLevel(logging.DEBUG)
        logging.getLogger("langchain").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)
    else:
        logging.getLogger("uvicorn").setLevel(logging.INFO)
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
        logging.getLogger("fastapi").setLevel(logging.INFO)
        logging.getLogger("langchain").setLevel(logging.INFO)
        logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Silence noisy model-encoding warnings from langchain_openai embeddings layer
    logging.getLogger("langchain_openai.embeddings.base").setLevel(logging.ERROR)
    # Silence filelock library debug messages (only show warnings/errors)
    logging.getLogger("filelock").setLevel(logging.WARNING)
    
    # Make uvicorn use our formatter for all its messages
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers.clear()
    uvicorn_logger.addHandler(console_handler)
    uvicorn_logger.addHandler(file_handler)
    uvicorn_logger.propagate = False  # Prevent double logging
    
    # Also capture uvicorn.error logger which handles WARNING messages
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_error_logger.handlers.clear()
    uvicorn_error_logger.addHandler(console_handler)
    uvicorn_error_logger.addHandler(file_handler)
    uvicorn_error_logger.propagate = False
    
    # Set our application logger
    app_logger = logging.getLogger("morpheus")
    app_logger.setLevel(min(console_level, file_level, log_level))
    
    # Log initialization
    app_logger.info(f'Logging initialized. Log file: {log_filename}')


# Context variable for per-request message correlation id
_message_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("message_id", default=None)
_route_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("route", default=None)
_ns_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("namespace", default=None)


def set_message_id(message_id: str | None) -> None:
    _message_id_var.set(message_id)


def get_message_id() -> str | None:
    return _message_id_var.get()


def clear_message_id() -> None:
    _message_id_var.set(None)


def set_route(route: str | None) -> None:
    _route_var.set(route)


def get_route() -> str | None:
    return _route_var.get()


def clear_route() -> None:
    _route_var.set(None)


def set_namespace(namespace: str | None) -> None:
    _ns_var.set(namespace)


def get_namespace() -> str | None:
    return _ns_var.get()


def clear_namespace() -> None:
    _ns_var.set(None)


def get_logger(name: str = None) -> logging.Logger:
    """Get the main application logger."""
    return logging.getLogger("morpheus")


class RequestLogger:
    """Request logging utility for API endpoints."""
    
    def __init__(self, logger_name: str = "api"):
        self.logger = get_logger()  # Use single shared logger
    
    def log_request(
        self, 
        endpoint: str, 
        method: str, 
        user_id: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log an incoming request."""
        self.logger.info(
            f"Request: {method} {endpoint}",
            extra={
                "endpoint": endpoint,
                "method": method,
                "user_id": user_id,
                "type": "request"
            }
        )
    
    def log_response(
        self, 
        endpoint: str, 
        status_code: int, 
        response_time: float,
        user_id: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log a response."""
        self.logger.debug(
            f"Response: {endpoint} -> {status_code} ({response_time:.3f}s)",
            extra={
                "endpoint": endpoint,
                "status_code": status_code,
                "response_time": response_time,
                "user_id": user_id,
                "type": "response"
            }
        )
    
    def log_error(
        self, 
        endpoint: str, 
        error: Exception, 
        user_id: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log an error."""
        self.logger.error(
            f"Error in {endpoint}: {str(error)}",
            extra={
                "endpoint": endpoint,
                "error": str(error),
                "error_type": type(error).__name__,
                "user_id": user_id,
                "type": "error"
            },
            exc_info=True
        )


class LLMLogger:
    """LLM-specific logging utility."""
    
    def __init__(self):
        self.logger = get_logger()  # Use single shared logger
    
    def log_llm_request(
        self, 
        model: str, 
        message_length: int, 
        conversation_id: Optional[str] = None
    ) -> None:
        """Log an LLM request."""
        self.logger.info(
            f"LLM Request: {model} (message: {message_length} chars)",
            extra={
                "model": model,
                "message_length": message_length,
                "conversation_id": conversation_id,
                "type": "llm_request"
            }
        )
    
    def log_llm_response(
        self, 
        model: str, 
        response_length: int, 
        tokens_used: Optional[int] = None,
        conversation_id: Optional[str] = None
    ) -> None:
        """Log an LLM response."""
        self.logger.info(
            f"LLM Response: {model} (response: {response_length} chars, tokens: {tokens_used})",
            extra={
                "model": model,
                "response_length": response_length,
                "tokens_used": tokens_used,
                "conversation_id": conversation_id,
                "type": "llm_response"
            }
        )
    
    def log_llm_error(
        self, 
        model: str, 
        error: Exception, 
        conversation_id: Optional[str] = None
    ) -> None:
        """Log an LLM error."""
        self.logger.error(
            f"LLM Error: {model} - {str(error)}",
            extra={
                "model": model,
                "error": str(error),
                "error_type": type(error).__name__,
                "conversation_id": conversation_id,
                "type": "llm_error"
            },
            exc_info=True
        )


# Logging setup is called explicitly from main.py
