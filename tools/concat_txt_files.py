#!/usr/bin/env python3
"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

Concatenate top-level .txt files from an input directory into one output file.
"""


import argparse
from pathlib import Path


OUTPUT_FILENAME = "concatenated_Syx.txt"


def _validate_input_dir(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Input path is not a directory: {path}")


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _iter_txt_files(path: Path) -> list[Path]:
    return sorted(
        [p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".txt"],
        key=lambda p: p.name.lower(),
    )


def run(input_dir_raw: str, output_dir_raw: str) -> Path:
    input_dir = Path(input_dir_raw).resolve()
    output_dir = Path(output_dir_raw).resolve()

    _validate_input_dir(input_dir)
    _ensure_output_dir(output_dir)

    txt_files = _iter_txt_files(input_dir)
    if not txt_files:
        raise RuntimeError(f"No .txt files found in input directory: {input_dir}")

    parts: list[str] = []
    for path in txt_files:
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed reading '{path}': {exc}") from exc

    combined = "\n".join(part.rstrip("\n") for part in parts) + "\n"
    out_path = output_dir / OUTPUT_FILENAME
    try:
        out_path.write_text(combined, encoding="utf-8", newline="\n")
    except Exception as exc:
        raise RuntimeError(f"Failed writing '{out_path}': {exc}") from exc

    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Concatenate top-level .txt files from input folder into concatenated_Syx.txt.",
    )
    parser.add_argument("input_dir", help="Directory containing .txt files to concatenate")
    parser.add_argument("output_dir", help="Directory where concatenated_Syx.txt will be written")
    args = parser.parse_args()

    try:
        out_path = run(args.input_dir, args.output_dir)
        print(f"Wrote: {out_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
