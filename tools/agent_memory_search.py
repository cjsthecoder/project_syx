#!/usr/bin/env python3
"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""CLI bridge for POST /agent/memory/search."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    token = args.agent_token if args.agent_token is not None else os.environ.get("SYX_AGENT_TOKEN")
    if token is None:
        print("agent token is required via --agent-token or SYX_AGENT_TOKEN", file=sys.stderr)
        return 2

    endpoint_url = args.base_url.rstrip("/") + "/agent/memory/search"
    request_payload = {
        "project_name": args.project_name,
        "query": args.query,
        "category": args.category or "OTHER",
        "agent_token": token,
    }
    if args.model:
        request_payload["model"] = args.model

    status_code = 0
    response_json: Dict[str, Any] = {}
    error_text = ""
    try:
        status_code, response_json = _post_json(endpoint_url, request_payload)
        output = json.dumps(response_json, ensure_ascii=False, indent=2 if args.pretty else None)
        print(output)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        error_text = exc.read().decode("utf-8", errors="replace")
        try:
            response_json = json.loads(error_text)
        except json.JSONDecodeError:
            response_json = {"error": "http_error", "message": error_text}
        print(json.dumps(response_json, ensure_ascii=False, indent=2 if args.pretty else None))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        error_text = str(exc)
        response_json = {"error": "request_failed", "message": error_text}
        print(json.dumps(response_json, ensure_ascii=False, indent=2 if args.pretty else None))
    finally:
        _write_debug_file(
            debug_dir=Path(args.debug_dir) if args.debug_dir else _default_debug_dir(),
            endpoint_url=endpoint_url,
            request_payload=request_payload,
            response_status=status_code,
            response_json=response_json,
            error_text=error_text,
        )

    if status_code < 200 or status_code >= 300:
        return 1
    if not isinstance(response_json, dict) or "snippets" not in response_json:
        return 1
    return 0


def _parse_args(argv: List[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call the local Syx agent memory search endpoint.")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--agent-token", default=None)
    parser.add_argument("--category", default="OTHER")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def _post_json(url: str, payload: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(data) if data.strip() else {}
        return int(resp.status), parsed


def _write_debug_file(
    *,
    debug_dir: Path,
    endpoint_url: str,
    request_payload: Dict[str, Any],
    response_status: int,
    response_json: Dict[str, Any],
    error_text: str,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"agent_memory_search_{ts}.json"
    body = {
        "request_timestamp": ts,
        "endpoint_url": endpoint_url,
        "request_json": request_payload,
        "response_status": response_status,
        "response_json": response_json,
        "prompt_shaped_text": _render_prompt_text(response_json),
        "snippet_count": int(response_json.get("snippet_count", 0) or 0),
        "memory_ids_returned": [
            snip.get("memory_id")
            for snip in response_json.get("snippets", [])
            if isinstance(snip, dict) and snip.get("memory_id")
        ],
        "bounded_result_count": int(response_json.get("bounded_result_count", 0) or 0),
        "unbounded_result_count": int(response_json.get("unbounded_result_count", 0) or 0),
        "error_text": error_text,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_prompt_text(response_json: Dict[str, Any]) -> str:
    snippets = response_json.get("snippets")
    if not isinstance(snippets, list):
        return ""
    pieces: List[str] = []
    for snip in snippets:
        if not isinstance(snip, dict):
            continue
        pieces.append(_render_snippet(snip))
    return ("Context:\n---\n" + "\n\n---\n".join(pieces)) if pieces else ""


def _render_snippet(snip: Dict[str, Any]) -> str:
    chunk = snip.get("chunk_index_range")
    if not chunk and snip.get("chunk_index_start") is not None and snip.get("chunk_index_end") is not None:
        if snip.get("chunk_index_start") == snip.get("chunk_index_end"):
            chunk = str(snip.get("chunk_index_start"))
        else:
            chunk = f"{snip.get('chunk_index_start')}..{snip.get('chunk_index_end')}"
    bits = [
        f"source={snip.get('source')}",
        _format_float("cos", snip.get("cos")),
        _format_float("score", snip.get("score")),
    ]
    if snip.get("source") == "daily":
        bits.append("route=None")
    else:
        bits.append(f"file={snip.get('file')}")
        bits.append(f"page={snip.get('page')}")
    bits.append(f"chunk_index={chunk}")
    return f"Snippet {snip.get('snippet_number')} ({', '.join(bits)})\n{snip.get('text') or ''}"


def _format_float(name: str, value: Any) -> str:
    try:
        return f"{name}={float(value):.4f}"
    except (TypeError, ValueError):
        return f"{name}=None"


def _default_debug_dir() -> Path:
    return Path(__file__).resolve().parent / "agent_interface"


if __name__ == "__main__":
    raise SystemExit(main())
