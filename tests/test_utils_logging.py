"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.utils.logging.

Covers the CustomFormatter color selection and the _supports_colors branches
(non-tty, known TERM, Windows console probe + AttributeError fallback, plain
fallback), setup_logging's DEBUG-level wiring (with the global logging state
snapshotted and restored), the context-var setters/clearers, and the
Request/LLM logger helpers. No real terminal or Windows API is touched.
"""
import logging
from types import SimpleNamespace

import app.utils.logging as logging_mod
import pytest
from app.utils.logging import (
    CustomFormatter,
    LLMLogger,
    RequestLogger,
    clear_message_id,
    clear_namespace,
    clear_route,
    get_logger,
    get_message_id,
    get_namespace,
    get_route,
    set_message_id,
    set_namespace,
    set_route,
    setup_logging,
)


def _tty(is_atty: bool):
    return SimpleNamespace(isatty=lambda: is_atty)


# --- CustomFormatter ----------------------------------------------------------


def test_custom_formatter_uses_colors_when_supported(monkeypatch):
    monkeypatch.setattr(CustomFormatter, "_supports_colors", lambda self: True)
    fmt = CustomFormatter()
    assert fmt.use_colors is True
    # Colored format strings carry ANSI escape codes.
    assert "\033[" in fmt.formats[logging.INFO]


def test_custom_formatter_plain_when_not_supported(monkeypatch):
    monkeypatch.setattr(CustomFormatter, "_supports_colors", lambda self: False)
    fmt = CustomFormatter()
    assert fmt.use_colors is False
    assert "\033[" not in fmt.formats[logging.INFO]


def test_custom_formatter_format_renders_record(monkeypatch):
    monkeypatch.setattr(CustomFormatter, "_supports_colors", lambda self: False)
    fmt = CustomFormatter()
    record = logging.LogRecord("syx", logging.WARNING, __file__, 1, "hello", None, None)
    out = fmt.format(record)
    assert "hello" in out and "WARNING" in out


def test_custom_formatter_format_unknown_level_falls_back_to_info(monkeypatch):
    monkeypatch.setattr(CustomFormatter, "_supports_colors", lambda self: False)
    fmt = CustomFormatter()
    record = logging.LogRecord("syx", 999, __file__, 1, "msg", None, None)
    assert "msg" in fmt.format(record)


# --- _supports_colors ---------------------------------------------------------


# Capture the real method so the tests below exercise the genuine logic even
# though construction-time calls to it are environment-dependent.
_REAL_SUPPORTS_COLORS = CustomFormatter._supports_colors


def test_supports_colors_false_when_not_a_tty(monkeypatch):
    fmt = CustomFormatter()
    monkeypatch.setattr(logging_mod.sys, "stdout", _tty(False))
    assert _REAL_SUPPORTS_COLORS(fmt) is False


def test_supports_colors_true_for_known_term(monkeypatch):
    fmt = CustomFormatter()
    monkeypatch.setattr(logging_mod.sys, "stdout", _tty(True))
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _REAL_SUPPORTS_COLORS(fmt) is True


def test_supports_colors_false_for_unknown_term_non_windows(monkeypatch):
    fmt = CustomFormatter()
    monkeypatch.setattr(logging_mod.sys, "stdout", _tty(True))
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(logging_mod.os, "name", "posix")
    assert _REAL_SUPPORTS_COLORS(fmt) is False


def test_supports_colors_windows_attribute_error_fallback(monkeypatch):
    fmt = CustomFormatter()
    monkeypatch.setattr(logging_mod.sys, "stdout", _tty(True))
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(logging_mod.os, "name", "nt")

    # kernel32 lacks GetStdHandle -> AttributeError inside the try -> False.
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=SimpleNamespace()))
    monkeypatch.setattr(logging_mod, "ctypes", fake_ctypes)
    assert _REAL_SUPPORTS_COLORS(fmt) is False


# --- setup_logging ------------------------------------------------------------


@pytest.fixture
def _restore_logging_state():
    """Snapshot and restore the global logging configuration around a test."""
    root = logging.getLogger()
    names = ["", "uvicorn", "uvicorn.error", "syx"]
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    saved_root_handlers = list(root.handlers)
    try:
        yield
    finally:
        for name, (handlers, level, propagate) in saved.items():
            lg = logging.getLogger(name)
            lg.handlers = list(handlers)
            lg.setLevel(level)
            lg.propagate = propagate
        root.handlers = saved_root_handlers


def _logging_settings(tmp_path, *, console="INFO", level="INFO"):
    return SimpleNamespace(
        log_level=level,
        log_level_console=console,
        log_level_file="DEBUG",
        logs_dir=str(tmp_path),
        log_file_prefix="test_",
        log_max_bytes=1_000_000,
        log_backup_count=1,
    )


def test_setup_logging_debug_branch(monkeypatch, tmp_path, _restore_logging_state):
    monkeypatch.setattr(
        logging_mod, "get_settings", lambda: _logging_settings(tmp_path, console="DEBUG")
    )
    setup_logging()
    # DEBUG branch tunes uvicorn to DEBUG.
    assert logging.getLogger("uvicorn").level == logging.DEBUG
    # A timestamped log file was created.
    assert any(p.name.startswith("test_") and p.suffix == ".log" for p in tmp_path.iterdir())


def test_setup_logging_info_branch(monkeypatch, tmp_path, _restore_logging_state):
    monkeypatch.setattr(
        logging_mod, "get_settings", lambda: _logging_settings(tmp_path, console="INFO")
    )
    setup_logging()
    assert logging.getLogger("uvicorn").level == logging.INFO
    assert logging.getLogger("filelock").level == logging.WARNING


# --- context vars -------------------------------------------------------------


def test_message_id_context_var():
    set_message_id("m1")
    assert get_message_id() == "m1"
    clear_message_id()
    assert get_message_id() is None


def test_route_context_var():
    set_route("DIRECT")
    assert get_route() == "DIRECT"
    clear_route()
    assert get_route() is None


def test_namespace_context_var():
    set_namespace("work")
    assert get_namespace() == "work"
    clear_namespace()
    assert get_namespace() is None


# --- get_logger / RequestLogger / LLMLogger ----------------------------------


def test_get_logger_returns_shared_syx_logger():
    assert get_logger("anything").name == "syx"
    assert get_logger() is logging.getLogger("syx")


def test_request_logger_helpers_emit(caplog):
    caplog.set_level(logging.DEBUG, logger="syx")
    rl = RequestLogger("api")
    rl.log_request(endpoint="/x", method="GET", user_id="u1")
    rl.log_response(endpoint="/x", status_code=200, response_time=0.123, user_id="u1")
    rl.log_error(endpoint="/x", error=ValueError("boom"), user_id="u1")
    messages = " ".join(r.message for r in caplog.records)
    assert "Request: GET /x" in messages
    assert "Response: /x -> 200" in messages
    assert "Error in /x: boom" in messages


def test_llm_logger_helpers_emit(caplog):
    caplog.set_level(logging.INFO, logger="syx")
    ll = LLMLogger()
    ll.log_llm_request(model="gpt", message_length=10, conversation_id="c1")
    ll.log_llm_response(model="gpt", response_length=20, tokens_used=5, conversation_id="c1")
    ll.log_llm_error(model="gpt", error=RuntimeError("kaboom"), conversation_id="c1")
    messages = " ".join(r.message for r in caplog.records)
    assert "LLM Request: gpt" in messages
    assert "LLM Response: gpt" in messages
    assert "LLM Error: gpt - kaboom" in messages
