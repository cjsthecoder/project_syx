"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Enhanced logging configuration for Syx AGI Chatbot Framework.

This module provides structured logging with colored console output and timestamped files.
"""

import contextvars
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

# Import ctypes for Windows color support
try:  # pragma: no cover - import success/failure is environment-dependent
    import ctypes  # pragma: no cover
except ImportError:  # pragma: no cover
    ctypes = None  # pragma: no cover

from ..core.config import get_settings


class CustomFormatter(logging.Formatter):  # pylint: disable=R0903
    """Level-aware console log formatter with optional ANSI coloring.

    Selects a per-level format string and applies ANSI color codes when the
    terminal is detected to support them, falling back to plain text otherwise
    (e.g. when output is redirected or on unsupported terminals).
    """

    # pylint: disable=C0301

    def __init__(self):
        super().__init__()
        # Check if terminal supports colors
        self.use_colors = self._supports_colors()

        if self.use_colors:
            self.formats = {
                logging.DEBUG: "\033[90m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m",
                logging.INFO: "\033[92m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m",
                logging.WARNING: "\033[93m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m",
                logging.ERROR: "\033[91m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m",
                logging.CRITICAL: "\033[95m%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s\033[0m",
            }
        else:
            # Fallback to plain text format
            self.formats = {
                logging.DEBUG: "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s",
                logging.INFO: "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s",
                logging.WARNING: "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s",
                logging.ERROR: "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s",
                logging.CRITICAL: "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s : %(message)s",
            }

    def _supports_colors(self):
        """Check if the terminal supports ANSI color codes.

        Returns:
            True when stdout is an interactive TTY with a known color-capable
            terminal type, or a Windows console with ANSI processing enabled;
            otherwise False.
        """
        # Check if we're in a terminal
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            return False

        # Check for common terminal types that support colors
        term = os.environ.get("TERM", "")
        if term in ("xterm", "xterm-256color", "linux", "screen", "screen-256color"):
            return True

        # Check for Windows 10+ with ANSI support
        if os.name == "nt" and ctypes:
            try:
                kernel32 = ctypes.windll.kernel32
                return (
                    kernel32.GetConsoleMode(kernel32.GetStdHandle(-11)) & 0x0004
                )  # pragma: no cover - Windows-specific API call
            except AttributeError:
                return False

        return False

    def format(self, record):
        """Render a log record using the level-specific (optionally colored) format.

        Args:
            record: The log record to format.

        Returns:
            The formatted log line, with ANSI color codes applied when the
            terminal supports them.
        """
        log_fmt = self.formats.get(record.levelno, self.formats[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def setup_logging() -> None:
    """Configure application-wide logging handlers and levels.

    Side effects: creates the logs directory, clears and reconfigures the root
    logger, attaches a rotating timestamped file handler plus a colored console
    handler, tunes third-party logger levels, and reroutes uvicorn logging
    through the shared handlers. Intended to be called once at startup.
    """

    settings = get_settings()
    # Legacy global level (retained for component loggers default)
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    # New per-handler levels
    console_level = getattr(logging, settings.log_level_console.upper(), logging.INFO)
    file_level = getattr(logging, settings.log_level_file.upper(), logging.DEBUG)

    # Create logs directory from runtime config (may be nested, e.g. tests/).
    logs_dir = str(settings.logs_dir)
    os.makedirs(logs_dir, exist_ok=True)

    # Create timestamped log filename. The prefix is configurable so test runs
    # can write 'test_<timestamp>.log' and keep them out of normal runtime logs.
    prefix = str(getattr(settings, "log_file_prefix", "syx_") or "syx_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(logs_dir, f"{prefix}{timestamp}.log")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    # Create rotating file handler (DEBUG level for detailed logs)
    file_handler = RotatingFileHandler(
        log_filename,
        maxBytes=int(settings.log_max_bytes),
        backupCount=int(settings.log_backup_count),
    )
    file_handler.setLevel(file_level)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s:%(funcName)s - %(message)s"
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
        logging.getLogger("openai").setLevel(logging.DEBUG)
    else:
        logging.getLogger("uvicorn").setLevel(logging.INFO)
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
        logging.getLogger("fastapi").setLevel(logging.INFO)
        logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
    app_logger = logging.getLogger("syx")
    app_logger.setLevel(min(console_level, file_level, log_level))

    # Log initialization
    app_logger.info(f"Logging initialized. Log file: {log_filename}")


# Context variable for per-request message correlation id
_message_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "message_id", default=None
)
_route_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("route", default=None)
_ns_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("namespace", default=None)


def set_message_id(message_id: str | None) -> None:
    """Bind the per-request message correlation id for the current context.

    Args:
        message_id: Correlation id to associate with the current execution
            context, or None to leave it unset.
    """
    _message_id_var.set(message_id)


def get_message_id() -> str | None:
    """Return the current context's message correlation id, if set."""
    return _message_id_var.get()


def clear_message_id() -> None:
    """Clear the current context's message correlation id."""
    _message_id_var.set(None)


def set_route(route: str | None) -> None:
    """Bind the active route label for the current context.

    Args:
        route: Route label to associate with the current execution context, or
            None to leave it unset.
    """
    _route_var.set(route)


def get_route() -> str | None:
    """Return the current context's route label, if set."""
    return _route_var.get()


def clear_route() -> None:
    """Clear the current context's route label."""
    _route_var.set(None)


def set_namespace(namespace: str | None) -> None:
    """Bind the active namespace for the current context.

    Args:
        namespace: Namespace to associate with the current execution context,
            or None to leave it unset.
    """
    _ns_var.set(namespace)


def get_namespace() -> str | None:
    """Return the current context's namespace, if set."""
    return _ns_var.get()


def clear_namespace() -> None:
    """Clear the current context's namespace."""
    _ns_var.set(None)


def get_logger(name: str = None) -> logging.Logger:
    """Get the main application logger.

    Args:
        name: Accepted for call-site compatibility; ignored so all callers share
            the single ``"syx"`` logger.

    Returns:
        The shared application logger instance.
    """
    return logging.getLogger("syx")


class RequestLogger:
    """Convenience wrapper for structured request/response logging in endpoints.

    Thin adapter over the shared application logger that provides consistent
    helpers for logging API requests, responses, and errors. It always writes
    through the single shared ``syx`` logger regardless of the name passed at
    construction.
    """

    def __init__(self, logger_name: str = "api"):
        """Initialize the request logger.

        Args:
            logger_name: Retained for call-site clarity; the shared application
                logger is used regardless of this value.
        """
        self.logger = get_logger()  # Use single shared logger

    def log_request(
        self, endpoint: str, method: str, user_id: Optional[str] = None, **kwargs
    ) -> None:
        """Log an incoming request at INFO level.

        Args:
            endpoint: The request path or endpoint name.
            method: The HTTP method (e.g. "GET", "POST").
            user_id: Identifier of the requesting user, if known.
            **kwargs: Additional contextual fields (currently unused).
        """
        self.logger.info(
            f"Request: {method} {endpoint}",
            extra={"endpoint": endpoint, "method": method, "user_id": user_id, "type": "request"},
        )

    def log_response(
        self,
        endpoint: str,
        status_code: int,
        response_time: float,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Log a completed response at DEBUG level.

        Args:
            endpoint: The request path or endpoint name.
            status_code: HTTP status code returned to the client.
            response_time: Wall-clock duration of the request, in seconds.
            user_id: Identifier of the requesting user, if known.
            **kwargs: Additional contextual fields (currently unused).
        """
        self.logger.debug(
            f"Response: {endpoint} -> {status_code} ({response_time:.3f}s)",
            extra={
                "endpoint": endpoint,
                "status_code": status_code,
                "response_time": response_time,
                "user_id": user_id,
                "type": "response",
            },
        )

    def log_error(
        self, endpoint: str, error: Exception, user_id: Optional[str] = None, **kwargs
    ) -> None:
        """Log an endpoint error at ERROR level with a traceback.

        Args:
            endpoint: The request path or endpoint name where the error arose.
            error: The exception that occurred; its type and message are recorded.
            user_id: Identifier of the requesting user, if known.
            **kwargs: Additional contextual fields (currently unused).
        """
        self.logger.error(
            f"Error in {endpoint}: {str(error)}",
            extra={
                "endpoint": endpoint,
                "error": str(error),
                "error_type": type(error).__name__,
                "user_id": user_id,
                "type": "error",
            },
            exc_info=True,
        )


class LLMLogger:
    """Convenience wrapper for logging LLM request/response activity.

    Thin adapter over the shared application logger offering helpers tailored to
    LLM calls (model, prompt size, latency, token usage). Writes through the
    single shared ``syx`` logger.
    """

    def __init__(self):
        self.logger = get_logger()  # Use single shared logger

    def log_llm_request(
        self, model: str, message_length: int, conversation_id: Optional[str] = None
    ) -> None:
        """Log an outbound LLM request at INFO level.

        Args:
            model: Name of the model being called.
            message_length: Length of the prompt/message, in characters.
            conversation_id: Identifier of the associated conversation, if any.
        """
        self.logger.info(
            f"LLM Request: {model} (message: {message_length} chars)",
            extra={
                "model": model,
                "message_length": message_length,
                "conversation_id": conversation_id,
                "type": "llm_request",
            },
        )

    def log_llm_response(
        self,
        model: str,
        response_length: int,
        tokens_used: Optional[int] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Log an LLM response at INFO level.

        Args:
            model: Name of the model that produced the response.
            response_length: Length of the response text, in characters.
            tokens_used: Total tokens consumed by the call, if reported.
            conversation_id: Identifier of the associated conversation, if any.
        """
        self.logger.info(
            f"LLM Response: {model} (response: {response_length} chars, tokens: {tokens_used})",
            extra={
                "model": model,
                "response_length": response_length,
                "tokens_used": tokens_used,
                "conversation_id": conversation_id,
                "type": "llm_response",
            },
        )

    def log_llm_error(
        self, model: str, error: Exception, conversation_id: Optional[str] = None
    ) -> None:
        """Log an LLM call failure at ERROR level with a traceback.

        Args:
            model: Name of the model that failed.
            error: The exception raised by the LLM call; its type and message
                are recorded.
            conversation_id: Identifier of the associated conversation, if any.
        """
        self.logger.error(
            f"LLM Error: {model} - {str(error)}",
            extra={
                "model": model,
                "error": str(error),
                "error_type": type(error).__name__,
                "conversation_id": conversation_id,
                "type": "llm_error",
            },
            exc_info=True,
        )


# Logging setup is called explicitly from main.py
