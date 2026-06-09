"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.utils.debug_utils.write_debug_file.

Covers the disabled no-op (GENERATE_DEBUG_FILES off), the enabled happy-path
write under memory/{project}/debug/, and the best-effort warning when the
write fails.
"""
from types import SimpleNamespace

import app.utils.debug_utils as debug_utils
from app.utils.debug_utils import write_debug_file


def test_write_debug_file_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        debug_utils,
        "get_settings",
        lambda: SimpleNamespace(generate_debug_files=False, memory_root=str(tmp_path)),
    )
    write_debug_file("p1", "debug_context.txt", "content")
    assert list(tmp_path.iterdir()) == []


def test_write_debug_file_writes_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        debug_utils,
        "get_settings",
        lambda: SimpleNamespace(generate_debug_files=True, memory_root=str(tmp_path)),
    )
    write_debug_file("p1", "debug_context.txt", "hello-debug")
    out = tmp_path / "p1" / "debug" / "debug_context.txt"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "hello-debug"


def test_write_debug_file_logs_on_write_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        debug_utils,
        "get_settings",
        lambda: SimpleNamespace(generate_debug_files=True, memory_root=str(tmp_path)),
    )

    def _boom(*_args, **_kwargs):
        raise OSError("makedirs failed")

    monkeypatch.setattr(debug_utils.os, "makedirs", _boom)
    with caplog.at_level("WARNING"):
        write_debug_file("p1", "debug_context.txt", "content")
    assert any("Failed writing debug file" in r.message for r in caplog.records)
