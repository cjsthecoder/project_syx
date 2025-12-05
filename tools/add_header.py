#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""



Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""


import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

HEADER_TEXT_LINES = [
    '"""',
    "",
    "",
    "",
    "Copyright (c) 2025 Syx Project Contributors. All rights reserved.",
    "",
    "This source code is part of the Morpheus project and is proprietary.",
    "",
    "Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.",
    "",
    "Use of this software requires explicit written permission from the copyright holder.",
    "",
    '"""',
    "",
    "",
]
HEADER_TEXT = "\n".join(HEADER_TEXT_LINES)

HEADER_TSJS_LINES = [
    "/**",
    " *",
    " *",
    " *",
    " * Copyright (c) 2025 Syx Project Contributors. All rights reserved.",
    " *",
    " * This source code is part of the Morpheus project and is proprietary.",
    " *",
    " * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.",
    " *",
    " * Use of this software requires explicit written permission from the copyright holder.",
    " */",
    "",
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


def file_has_header_py(content: str) -> bool:
    return "Syx Project Contributors" in content and content.lstrip().startswith('"""')


def file_has_header_tsjs(content: str) -> bool:
    stripped = content.lstrip()
    return "Syx Project Contributors" in content and (stripped.startswith("/**") or stripped.startswith("/*"))


def insert_header_python(content: str) -> str:
    # Preserve shebang or encoding line if present
    lines = content.splitlines(keepends=True)
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
        # Keep encoding line as second line if present
        if len(lines) > 1 and lines[1].startswith("# -*- coding:"):
            idx = 2
    new_content = "".join(lines[:idx]) + HEADER_TEXT + "".join(lines[idx:])
    return new_content


def insert_header_tsjs(content: str) -> str:
    return HEADER_TSJS + content


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
            return False
        new_content = insert_header_python(content)
    else:
        if file_has_header_tsjs(content):
            return False
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


