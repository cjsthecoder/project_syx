#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Add standard copyright headers to project files.
"""


import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Markers that identify a header block as ours. Detection keys off these so the
# tool can normalize existing headers and remain idempotent across runs.
HEADER_MARKERS = ("Syx Project Contributors", "SPDX-License-Identifier: MIT")


def _has_header_marker(text: str) -> bool:
    return any(marker in text for marker in HEADER_MARKERS)


HEADER_TEXT_LINES = [
    '"""',
    "SPDX-License-Identifier: MIT",
    "",
    "This file is part of the Syx project. See the LICENSE file in the project",
    "root for full license information.",
    '"""',
    "",
]
HEADER_TEXT = "\n".join(HEADER_TEXT_LINES)
# Inner body lines (between the triple quotes), used to strip lingering header
# lines from a following module docstring. Slicing off the opening quote and the
# trailing quote/blank keeps this correct regardless of header length.
HEADER_BODY_LINES = set(HEADER_TEXT_LINES[1:-2])

HEADER_TSJS_LINES = [
    "/**",
    " * SPDX-License-Identifier: MIT",
    " *",
    " * This file is part of the Syx project. See the LICENSE file in the project",
    " * root for full license information.",
    " */",
    "",
]
HEADER_TSJS = "\n".join(HEADER_TSJS_LINES)

SKIP_DIRS = {
    ".git",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
    "__pycache__",
    "backend/app/static",  # built frontend assets
}

PY_EXTS = {".py"}
FE_EXTS = {".ts", ".tsx", ".js", ".jsx"}


def should_skip_dir(path: str) -> bool:
    parts = set(os.path.normpath(path).split(os.sep))
    return any(skip in parts for skip in SKIP_DIRS)


def python_preamble_index(content: str) -> int:
    lines = content.splitlines(keepends=True)
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if len(lines) > idx and lines[idx].startswith("# -*- coding:"):
        idx += 1
    return len("".join(lines[:idx]))


def file_has_header_py(content: str) -> bool:
    start = python_preamble_index(content)
    return content[start:].lstrip().startswith('"""') and _has_header_marker(content[start:])


def file_has_header_tsjs(content: str) -> bool:
    stripped = content.lstrip()
    return _has_header_marker(content) and (stripped.startswith("/**") or stripped.startswith("/*"))


def insert_header_python(content: str) -> str:
    idx = python_preamble_index(content)
    return content[:idx] + HEADER_TEXT + content[idx:]


def insert_header_tsjs(content: str) -> str:
    return HEADER_TSJS + content


def normalize_existing_tsjs_header(content: str) -> str:
    """
    If the file already has our header at the very top but with extra blank '*'
    lines, replace the first comment block with the normalized HEADER_TSJS.
    """
    stripped_leading = content.lstrip()
    leading_ws_len = len(content) - len(stripped_leading)
    leading_ws = content[:leading_ws_len]
    # Work only if the very first non-whitespace starts a block comment
    if not stripped_leading.startswith("/**"):
        return content
    end = stripped_leading.find("*/")
    if end == -1:
        return content
    block = stripped_leading[: end + 2]
    if not _has_header_marker(block):
        return content
    # Replace the entire leading block with normalized header
    remainder = stripped_leading[end + 2 :]
    # Ensure remainder starts with at most one newline
    remainder = remainder.lstrip("\n")
    return leading_ws + HEADER_TSJS + remainder


def normalize_existing_py_header(content: str) -> str:
    """
    If the file already has our Python header at the very top but with extra
    blank lines before the copyright, replace the first triple-quoted block
    with the normalized HEADER_TEXT (no leading blank lines).
    """
    preamble_end = python_preamble_index(content)
    preamble = content[:preamble_end]
    stripped_leading = content[preamble_end:].lstrip()
    leading_ws_len = len(content[preamble_end:]) - len(stripped_leading)
    leading_ws = content[preamble_end : preamble_end + leading_ws_len]
    if not stripped_leading.startswith('"""'):
        return content
    # find closing triple quotes
    end = stripped_leading.find('"""', 3)
    if end == -1:
        return content
    block = stripped_leading[: end + 3]
    if not _has_header_marker(block):
        return content
    remainder = stripped_leading[end + 3 :]
    remainder = remainder.lstrip("\n")
    return preamble + leading_ws + HEADER_TEXT + remainder


def remove_duplicate_py_header_docstring(content: str) -> str:
    """Remove a second copyright docstring after the normalized header, preserving real docs."""
    preamble_end = python_preamble_index(content)
    preamble = content[:preamble_end]
    tail = content[preamble_end:]
    if not tail.startswith(HEADER_TEXT):
        return content
    remainder = tail[len(HEADER_TEXT) :]
    if not remainder.startswith('"""'):
        return content
    end = remainder.find('"""', 3)
    if end == -1:
        return content
    block_text = remainder[3:end]
    if not _has_header_marker(block_text):
        return content
    filtered = [line for line in block_text.splitlines() if line not in HEADER_BODY_LINES]
    doc_text = "\n".join(filtered).strip("\n")
    after = remainder[end + 3 :].lstrip("\n")
    if not doc_text:
        return preamble + HEADER_TEXT + after
    return preamble + HEADER_TEXT + f'"""\n{doc_text}\n"""\n\n' + after


def process_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    is_py = ext in PY_EXTS
    is_fe = ext in FE_EXTS and os.path.normpath(path).startswith(
        os.path.join(REPO_ROOT, "frontend")
    )
    if not (is_py or is_fe):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False
    if is_py:
        if file_has_header_py(content):
            new_content = normalize_existing_py_header(content)
        else:
            new_content = insert_header_python(content)
        new_content = remove_duplicate_py_header_docstring(new_content)
        if new_content == content:
            return False
    else:
        if file_has_header_tsjs(content):
            # Normalize existing header to remove extra blank '*' lines
            new_content = normalize_existing_tsjs_header(content)
            if new_content == content:
                return False
        else:
            new_content = insert_header_tsjs(content)
    if new_content != content:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)
        return True
    return False


def main() -> int:
    changed = 0
    for root, dirs, files in os.walk(REPO_ROOT):
        if should_skip_dir(root):
            # Prune traversal of skipped directories
            dirs[:] = []
            continue
        for name in files:
            path = os.path.join(root, name)
            if process_file(path):
                changed += 1
    print(f"Updated headers in {changed} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


