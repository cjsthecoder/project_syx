from __future__ import annotations

import re

_INTERNAL_SPACES_RE = re.compile(r"[ \t]+")


def compact_whitespace(text: str) -> str:
    if not text or text.strip() == "":
        return ""

    output_chunks: list[str] = []
    in_code_block = False
    previous_prose_blank = False

    for line in text.splitlines(keepends=True):
        trimmed_line = line.rstrip("\r\n").strip()
        is_fence_line = trimmed_line.startswith("```")

        if in_code_block:
            output_chunks.append(line)
            if is_fence_line:
                in_code_block = False
            continue

        if is_fence_line:
            in_code_block = True
            previous_prose_blank = False
            output_chunks.append(line)
            continue

        prose_line = _normalize_prose_line(line)
        if prose_line is None:
            if previous_prose_blank:
                continue
            previous_prose_blank = True
            output_chunks.append("\n")
            continue

        previous_prose_blank = False
        output_chunks.append(prose_line)

    return "".join(output_chunks).strip()


def _normalize_prose_line(line: str) -> str | None:
    has_linebreak = line.endswith(("\r\n", "\n", "\r"))
    without_linebreak = line.rstrip("\r\n")
    without_trailing = without_linebreak.rstrip(" \t")
    collapsed_internal = _INTERNAL_SPACES_RE.sub(" ", without_trailing)

    if collapsed_internal.strip() == "":
        return None

    if has_linebreak:
        return f"{collapsed_internal}\n"
    return collapsed_internal
