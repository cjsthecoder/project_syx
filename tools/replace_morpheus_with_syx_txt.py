#!/usr/bin/env python3
"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Replace every case-insensitive occurrence of "Morpheus" with "Syx" in top-level .txt files.
- Input: one directory; only immediate children named *.txt are processed (no recursion).
- Files are rewritten in place only when the content changes.
"""

import argparse
import logging
import re
import sys
from pathlib import Path


logger = logging.getLogger("replace_morpheus_with_syx_txt")

_MORPHEUS = re.compile(r"Morpheus", re.IGNORECASE)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _validate_dir(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")


def _iter_txt_files(directory: Path) -> list[Path]:
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
    return sorted(files, key=lambda p: p.name.lower())


def _process_file(path: Path, *, dry_run: bool) -> tuple[int, bool]:
    """Returns (replacement_count, would_change_or_changed)."""
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("read failed path=%s", path, exc_info=exc)
        return 0, False
    except UnicodeDecodeError as exc:
        logger.warning("not valid utf-8 path=%s", path, exc_info=exc)
        return 0, False

    def _repl(_m: re.Match[str]) -> str:
        return "Syx"

    new, n = _MORPHEUS.subn(_repl, original)
    if n == 0:
        return 0, False
    if dry_run:
        logger.info("dry-run would replace %d occurrence(s) in %s", n, path)
        return n, True
    try:
        path.write_text(new, encoding="utf-8", newline="")
    except OSError as exc:
        logger.warning("write failed path=%s", path, exc_info=exc)
        return n, False
    logger.info("updated %s (%d replacement(s))", path, n)
    return n, True


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        description='Replace "Morpheus" (any case) with "Syx" in each .txt file in a directory (non-recursive).',
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing .txt files (only top-level files are scanned).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing files.",
    )
    args = parser.parse_args(argv)

    directory = args.directory.resolve()
    try:
        _validate_dir(directory)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    paths = _iter_txt_files(directory)
    if not paths:
        logger.info("no .txt files in %s", directory)
        return 0

    total_replacements = 0
    files_touched = 0
    for path in paths:
        count, changed = _process_file(path, dry_run=bool(args.dry_run))
        total_replacements += count
        if changed:
            files_touched += 1

    mode = "dry-run" if args.dry_run else "done"
    logger.info(
        "%s: %d file(s) with matches, %d total replacement(s)",
        mode,
        files_touched,
        total_replacements,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
