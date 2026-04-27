#!/usr/bin/env python3
"""
Import ChatGPT HTML exports into Syx daily-memory text format.

Behavior:
- Accept an input path that may be one HTML file or a directory.
- For directory mode, process only top-level .html/.htm files (no recursion)
  in native directory iteration order.
- Extract USER/ASSISTANT messages from HTML.
- Pair turns using extract_chat.py semantics:
  - pair USER with the next ASSISTANT
  - skip orphan ASSISTANT turns
  - replace unanswered USER with newer USER
- Tag each pair via backend.app.tagging.tagger.tag_pair() unless tagger=false.
- Write <output_dir>/<input_root>.txt in daily.txt-compatible format:
  - BEGIN DAILY MEMORY header
  - BEGIN/END DAILY PAIR blocks
  - END DAILY MEMORY footer
- Append one JSON object per successful file to <output_dir>/statistics.jsonl.
- If multiple files are processed in one run, also write one concatenated
  output file in <output_dir>/concatenated_daily.txt.
"""


import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger("import_chat_html_to_daily")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_import_paths() -> None:
    """
    Ensure script can import backend modules when executed from tools/.
    """
    repo_root = _repo_root_from_this_file()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parent.parent

def _require_dependencies() -> tuple[Any, Any]:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'bs4'. Install backend dependencies before running this tool."
        ) from exc
    try:
        import tiktoken  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'tiktoken'. Install backend dependencies before running this tool."
        ) from exc
    return BeautifulSoup, tiktoken


def _require_tagger() -> Any:
    try:
        from backend.app.tagging.tagger import tag_pair  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Failed importing backend.app.tagging.tagger.tag_pair. "
            "Run from repository context with backend dependencies configured."
        ) from exc
    return tag_pair


def _parse_bool_flag(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for tagger: {value!r}. Use true or false.")


def _estimate_tokens(text: str, enc: Any) -> int:
    return len(enc.encode(str(text or "")))


def _read_html(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed reading HTML file '{path}': {exc}") from exc


def _extract_messages(html_text: str, bs4_type: Any) -> list[tuple[str, str]]:
    """
    Extract ordered role/text messages from ChatGPT HTML.
    """
    soup = bs4_type(html_text, "html.parser")
    messages: list[tuple[str, str]] = []
    for div in soup.find_all("div", attrs={"data-message-author-role": True}):
        role = str(div.get("data-message-author-role") or "").upper().strip()
        if role not in {"USER", "ASSISTANT"}:
            continue
        text = div.get_text(strip=True)
        if text:
            messages.append((role, text))
    return messages


def _pair_turns(messages: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """
    Same pairing semantics used by tools/extract_chat.py.
    """
    pairs: list[tuple[str, str]] = []
    stats = {
        "orphan_assistant": 0,
        "replaced_unanswered_user": 0,
        "trailing_unanswered_user": 0,
    }
    pending_user: Optional[str] = None

    for role, text in messages:
        if role == "USER":
            if pending_user is not None:
                stats["replaced_unanswered_user"] += 1
            pending_user = text
            continue
        # ASSISTANT
        if pending_user is None:
            stats["orphan_assistant"] += 1
            continue
        pairs.append((pending_user, text))
        pending_user = None

    if pending_user is not None:
        stats["trailing_unanswered_user"] += 1

    return pairs, stats


def _extract_dd_trace_ms(html_text: str) -> Optional[int]:
    m = re.search(r'<meta\s+name="dd-trace-time"\s+content="(\d+)"', html_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception as exc:
        logger.warning("Invalid dd-trace-time content '%s': %s", m.group(1), exc)
        return None


def _resolve_time_basis(html_text: str) -> tuple[datetime, str]:
    """
    Returns:
      - local datetime basis
      - source label
    """
    ms = _extract_dd_trace_ms(html_text)
    if ms is not None:
        try:
            return datetime.fromtimestamp(ms / 1000.0), "dd-trace-time"
        except Exception as exc:
            logger.warning("Failed converting dd-trace-time=%s to datetime: %s", ms, exc)
    return datetime.now(), "now"


def _to_daily_header_date(dt_local: datetime) -> str:
    return dt_local.strftime("%m/%d/%Y")


def _to_daily_pair_timestamp(dt_local: datetime) -> str:
    return dt_local.strftime("%m-%d-%Y_%H:%M:%S")


def _normalize_tag_value(tag_data: Optional[dict[str, Any]], key: str) -> str:
    if not isinstance(tag_data, dict):
        return ""
    raw = tag_data.get(key, "")
    if raw is None:
        return ""
    return str(raw)


def _build_previous_pair_text(
    *,
    user_text: str,
    assistant_text: str,
    topics: str,
    intent: str,
    tag_type: str,
    semantic_handle: str,
) -> str:
    return (
        "#route: other\n"
        "#keep: false\n"
        f"#topics: {topics}\n"
        f"#intent: {intent}\n"
        f"#type: {tag_type}\n"
        f"#semantic_handle: {semantic_handle}\n\n"
        f"User: {user_text}\n"
        f"Assistant: {assistant_text}"
    )


def _build_daily_pair_block(
    *,
    pair_timestamp: str,
    user_text: str,
    assistant_text: str,
    topics: str,
    intent: str,
    tag_type: str,
    semantic_handle: str,
) -> str:
    return (
        "=== BEGIN DAILY PAIR ===\n"
        f"#timestamp: {pair_timestamp}\n"
        "#route: other\n"
        "#keep: false\n"
        f"#topics: {topics}\n"
        f"#intent: {intent}\n"
        f"#type: {tag_type}\n"
        f"#semantic_handle: {semantic_handle}\n"
        "\n"
        "--- USER (data-message-author-role: user) ---\n"
        f"{user_text}\n"
        "\n"
        "*** ASSISTANT (data-message-author-role: assistant) ***\n"
        f"{assistant_text}\n"
        "\n"
        "=== END DAILY PAIR ===\n"
    )


def _ensure_output_dir(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Output directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Output path is not a directory: {path}")


def _is_html_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".html", ".htm"}


def _validate_input_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")
    if not _is_html_file(path):
        raise ValueError(f"Unsupported input extension '{path.suffix.lower()}'. Expected .html/.htm")


def _process_one_file(
    *,
    input_path: Path,
    out_dir: Path,
    BeautifulSoup: Any,
    tag_pair: Optional[Any],
    encoding: Any,
) -> Path:
    html_text = _read_html(input_path)
    messages = _extract_messages(html_text, BeautifulSoup)
    if not messages:
        raise RuntimeError("No role-tagged USER/ASSISTANT messages found in input HTML.")

    pairs, pair_stats = _pair_turns(messages)
    if not pairs:
        raise RuntimeError("No valid USER->ASSISTANT pairs found after pairing.")

    file_dt_local, ts_source = _resolve_time_basis(html_text)
    daily_date = _to_daily_header_date(file_dt_local)
    pair_ts = _to_daily_pair_timestamp(file_dt_local)

    root = input_path.stem
    out_txt_path = out_dir / f"{root}.txt"
    stats_path = out_dir / "statistics.jsonl"

    blocks: list[str] = [f"=== BEGIN DAILY MEMORY: {daily_date} ===\n"]
    previous_pair_text: Optional[str] = None

    total_tokens_user_assistant = 0
    total_tokens_full_output = _estimate_tokens(blocks[0], encoding)

    for idx, (user_text, assistant_text) in enumerate(pairs, start=1):
        total_tokens_user_assistant += _estimate_tokens(user_text, encoding)
        total_tokens_user_assistant += _estimate_tokens(assistant_text, encoding)

        if tag_pair is not None:
            tags = tag_pair(
                user_text=user_text,
                assistant_text=assistant_text,
                previous_pair_text=previous_pair_text,
                project_id=f"html-import:{root}",
            )
            if not isinstance(tags, dict):
                raise RuntimeError(
                    f"tag_pair failed for pair #{idx}. "
                    "Tagger requires valid backend configuration/API key."
                )
        else:
            tags = {}

        topics = _normalize_tag_value(tags, "topics")
        intent = _normalize_tag_value(tags, "intent")
        tag_type = _normalize_tag_value(tags, "type")
        semantic_handle = _normalize_tag_value(tags, "semantic_handle")

        block = _build_daily_pair_block(
            pair_timestamp=pair_ts,
            user_text=user_text,
            assistant_text=assistant_text,
            topics=topics,
            intent=intent,
            tag_type=tag_type,
            semantic_handle=semantic_handle,
        )
        blocks.append("\n" + block)
        total_tokens_full_output += _estimate_tokens("\n" + block, encoding)

        previous_pair_text = _build_previous_pair_text(
            user_text=user_text,
            assistant_text=assistant_text,
            topics=topics,
            intent=intent,
            tag_type=tag_type,
            semantic_handle=semantic_handle,
        )

    end_marker = f"\n=== END DAILY MEMORY: {daily_date} ===\n"
    blocks.append(end_marker)
    total_tokens_full_output += _estimate_tokens(end_marker, encoding)

    output_text = "".join(blocks)
    try:
        out_txt_path.write_text(output_text, encoding="utf-8", newline="\n")
    except Exception as exc:
        raise RuntimeError(f"Failed writing output text file '{out_txt_path}': {exc}") from exc

    stats_record = {
        "ts": datetime.now().isoformat(),
        "filename_root": root,
        "input_file": str(input_path),
        "output_file": str(out_txt_path),
        "pairs_total": len(pairs),
        "tokens_user_assistant_total_est": int(total_tokens_user_assistant),
        "tokens_output_total_est": int(total_tokens_full_output),
        "timestamp_source": ts_source,
        "pairing_stats": pair_stats,
    }
    try:
        with open(stats_path, "a", encoding="utf-8", newline="\n") as sf:
            sf.write(json.dumps(stats_record, ensure_ascii=False) + "\n")
    except Exception as exc:
        raise RuntimeError(f"Failed appending statistics JSONL '{stats_path}': {exc}") from exc

    logger.info("Processed file: %s", input_path.name)
    logger.info("Pairs written: %s", len(pairs))
    logger.info("Output text: %s", out_txt_path)
    logger.info("Stats appended: %s", stats_path)
    return out_txt_path


def _write_concatenated_output(out_dir: Path, output_files: list[Path]) -> Path:
    concat_path = out_dir / "concatenated_daily.txt"
    parts: list[str] = []
    for p in output_files:
        try:
            parts.append(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed reading generated output '{p}' for concatenation: {exc}") from exc
    combined = "\n".join(part.rstrip() for part in parts) + "\n"
    try:
        concat_path.write_text(combined, encoding="utf-8", newline="\n")
    except Exception as exc:
        raise RuntimeError(f"Failed writing concatenated output '{concat_path}': {exc}") from exc
    return concat_path


def run(input_path_raw: str, output_dir: str, tagger: bool = True) -> int:
    _setup_logging()
    _ensure_import_paths()

    input_path = Path(input_path_raw).resolve()
    out_dir = Path(output_dir).resolve()
    _ensure_output_dir(out_dir)

    BeautifulSoup, tiktoken = _require_dependencies()
    tag_pair = _require_tagger() if tagger else None
    encoding = tiktoken.get_encoding("cl100k_base")

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    files_to_process: list[Path] = []
    if input_path.is_file():
        _validate_input_file(input_path)
        files_to_process = [input_path]
    elif input_path.is_dir():
        files_to_process = [p.resolve() for p in input_path.iterdir() if _is_html_file(p)]
        if not files_to_process:
            raise RuntimeError(f"No .html/.htm files found in directory: {input_path}")
    else:
        raise ValueError(f"Input path is neither a file nor directory: {input_path}")

    processed_count = 0
    failed_count = 0
    generated_output_files: list[Path] = []
    for fpath in files_to_process:
        try:
            output_file = _process_one_file(
                input_path=fpath,
                out_dir=out_dir,
                BeautifulSoup=BeautifulSoup,
                tag_pair=tag_pair,
                encoding=encoding,
            )
            processed_count += 1
            generated_output_files.append(output_file)
        except Exception as exc:
            failed_count += 1
            logger.warning("Failed processing file '%s': %s", fpath.name, exc)

    concat_failed = False
    if len(generated_output_files) > 1:
        try:
            concat_path = _write_concatenated_output(out_dir, generated_output_files)
            logger.info("Wrote concatenated output: %s", concat_path)
        except Exception as exc:
            concat_failed = True
            logger.warning("Failed writing concatenated output file: %s", exc)

    logger.info(
        "Run complete. processed=%s failed=%s input=%s tagger=%s",
        processed_count,
        failed_count,
        input_path,
        tagger,
    )
    return 0 if (failed_count == 0 and not concat_failed) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import ChatGPT HTML file(s) into Syx daily-memory text format."
    )
    parser.add_argument(
        "input_path",
        help="Path to one .html/.htm file or a directory of top-level .html/.htm files",
    )
    parser.add_argument("output_dir", help="Output directory for <root>.txt and statistics.jsonl")
    parser.add_argument(
        "tagger",
        nargs="?",
        default="true",
        help="Whether to run the tagger (true/false). Defaults to true.",
    )
    args = parser.parse_args()
    try:
        return run(args.input_path, args.output_dir, _parse_bool_flag(args.tagger))
    except Exception as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

