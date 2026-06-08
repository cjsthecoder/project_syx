"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Dream cycle orchestration for the Syx AGI Chatbot Framework.

Runs the post-sleep Dream pipeline (questions, idea, and research agents),
bridges remote-research questions into idea items, and serializes the final
dream.json output along with debug artifacts.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from ..core.config import get_settings
from .agents.questions_agent import run_questions_agent
from .agents.idea_agent import run_idea_agent
from .agents.research_agent import run_research_agent
from .context import build_dream_context
from app.utils.debug_utils import write_debug_file

logger = logging.getLogger(__name__)


def _dream_file_timestamp() -> str:
    """Filesystem-safe timestamp (matches prompts debug style)."""
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _normalize_text_key(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"['\"`“”’]", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return lowered.strip()


def _question_key_equivalent(a: str, b: str) -> bool:
    """Return True if two question strings are equivalent under fuzzy containment.

    Treats normalized strings as equivalent when they match exactly or when one
    sufficiently long phrasing contains the other.
    """
    ak = _normalize_text_key(a)
    bk = _normalize_text_key(b)
    if not ak or not bk:
        return False
    if ak == bk:
        return True
    # Accept close variants where one phrasing contains the other.
    if len(ak) >= 24 and bk in ak:
        return True
    if len(bk) >= 24 and ak in bk:
        return True
    return False


def _read_json_file_safe(path: str) -> Any:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("[DREAM][DEBUG] Failed reading json file path=%s err=%s", path, exc)
        return None


def _write_dreaming_debug_txt(
    project_id: str,
    debug_ts: str,
    suffix: str,
    sections: List[Tuple[str, str]],
) -> None:
    body_lines: List[str] = [
        f"# timestamp: {debug_ts}",
        f"# project_id: {project_id}",
        "",
    ]
    for title, content in sections:
        body_lines.append(f"====== {title} ======")
        body_lines.append(str(content or ""))
        body_lines.append("")
    write_debug_file(project_id, f"dreaming/{debug_ts}_{suffix}.txt", "\n".join(body_lines).rstrip() + "\n")


def _build_research_plan_rows(idea_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten idea items into one debug row per recommended research topic."""
    rows: List[Dict[str, Any]] = []
    items = idea_data.get("items") if isinstance(idea_data, dict) else []
    if not isinstance(items, list):
        return rows
    for it in items:
        if not isinstance(it, dict):
            continue
        md = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        rec = md.get("recommended_research")
        topics = rec if isinstance(rec, list) else ([rec] if rec not in (None, "", []) else [])
        for t in topics:
            topic = str(t or "").strip()
            if not topic:
                continue
            rows.append(
                {
                    "item_id": str(it.get("id", "") or ""),
                    "origin_text": str(it.get("origin_text", "") or ""),
                    "theme": str(md.get("theme", "") or ""),
                    "research_topic": topic,
                }
            )
    return rows


def _extract_question_resolution_rows(questions_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract (question, resolution) rows, keeping only recognized resolutions."""
    rows: List[Dict[str, str]] = []
    question_rows = questions_data.get("questions") if isinstance(questions_data, dict) else []
    if not isinstance(question_rows, list):
        return rows
    for q in question_rows:
        if not isinstance(q, dict):
            continue
        question = str(q.get("question", "") or "").strip()
        resolution = str(q.get("resolution", "") or "").strip().lower()
        if not question:
            continue
        if resolution not in {"ignore", "answer_local", "answer_remote"}:
            continue
        rows.append({"question": question, "resolution": resolution})
    return rows


def _attach_source_resolution_to_items(
    idea_data: Dict[str, Any],
    questions_data: Dict[str, Any],
) -> Dict[str, int]:
    """
    Attach source_resolution to Dream items when they can be mapped to question rows.
    This value is used downstream to drive persistence/formatting behavior.
    """
    items = idea_data.get("items") if isinstance(idea_data, dict) else []
    if not isinstance(items, list):
        return {"total_items": 0, "resolved_items": 0}
    q_rows = _extract_question_resolution_rows(questions_data)
    if not q_rows:
        return {"total_items": len(items), "resolved_items": 0}

    by_key: Dict[str, str] = {}
    for row in q_rows:
        key = _normalize_text_key(row["question"])
        if key:
            by_key[key] = row["resolution"]

    resolved_items = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        origin_text = str(it.get("origin_text", "") or "").strip()
        if not origin_text:
            continue
        k = _normalize_text_key(origin_text)
        resolved = by_key.get(k) if k else None
        if not resolved:
            for row in q_rows:
                if _question_key_equivalent(origin_text, row["question"]):
                    resolved = row["resolution"]
                    break
        if resolved:
            it["source_resolution"] = resolved
            resolved_items += 1
    return {"total_items": len(items), "resolved_items": resolved_items}


def _filter_idea_items_to_known_questions(
    idea_data: Dict[str, Any],
    questions_data: Dict[str, Any],
) -> Dict[str, int]:
    """
    Keep Idea items only when they map to a known consolidated question row.
    This prevents Idea output drift from introducing unrelated open questions.
    """
    items = idea_data.get("items") if isinstance(idea_data, dict) else []
    if not isinstance(items, list):
        return {"before": 0, "after": 0, "dropped": 0}
    q_rows = _extract_question_resolution_rows(questions_data)
    if not q_rows:
        idea_data["items"] = []
        return {"before": len(items), "after": 0, "dropped": len(items)}

    kept: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        origin_text = str(it.get("origin_text", "") or "").strip()
        if not origin_text:
            continue
        matched = False
        for row in q_rows:
            if _question_key_equivalent(origin_text, row["question"]):
                matched = True
                break
        if matched:
            kept.append(it)

    before = len(items)
    after = len(kept)
    idea_data["items"] = kept
    return {"before": before, "after": after, "dropped": max(0, before - after)}


def _build_synthetic_open_question_item(question_obj: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """Build an idea/research-compatible item from a remote-research question.

    Args:
        question_obj: Source question row carrying question/topic/answer fields.
        idx: One-based index used to make the synthetic item id unique.
    """
    q_text = str(question_obj.get("question", "") or "").strip()
    topic = str(question_obj.get("topic", "") or "").strip()
    answer = str(question_obj.get("answer", "") or "").strip()
    ts_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Keep schema-compatible shape for idea/research stages.
    return {
        "id": f"de-remoteq-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{idx:02d}",
        "agent": "idea_agent",
        "timestamp": ts_iso,
        "origin_text": q_text,
        "origin_type": "Open Question",
        "source_resolution": "answer_remote",
        "assistant_response": answer or "Question processed by Questions Agent.",
        "context_link": "Generated from Questions Agent remote-research output.",
        "metadata": {
            "priority": 1,
            "confidence": 0.30,
            "theme": topic or "open_question",
            "recommended_research": [q_text] if q_text else [],
        },
    }


def _bridge_remote_questions_into_ideas(
    ideas: Dict[str, Any],
    questions_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Ensure remote-backed question outputs are represented in idea_data so Research Agent
    can persist them into dream.json under item-level `research`.
    """
    items = ideas.get("items")
    if not isinstance(items, list):
        items = []
        ideas["items"] = items
    question_rows = questions_data.get("questions") if isinstance(questions_data, dict) else []
    if not isinstance(question_rows, list):
        question_rows = []

    remote_rows = [
        q for q in question_rows
        if isinstance(q, dict) and bool(q.get("used_remote_research", False)) and str(q.get("question", "") or "").strip()
    ]

    matched = 0
    injected = 0
    seeded_topics = 0
    decisions: List[Dict[str, Any]] = []

    by_origin_key: Dict[str, Dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        k = _normalize_text_key(str(it.get("origin_text", "") or ""))
        if k:
            by_origin_key[k] = it

    for idx, qobj in enumerate(remote_rows, start=1):
        q_text = str(qobj.get("question", "") or "").strip()
        key = _normalize_text_key(q_text)
        target = by_origin_key.get(key) if key else None
        matched_key = key
        if target is None and key:
            for existing_key, existing_item in by_origin_key.items():
                if _question_key_equivalent(key, existing_key):
                    target = existing_item
                    matched_key = existing_key
                    break
        if isinstance(target, dict):
            matched += 1
            target["source_resolution"] = "answer_remote"
            metadata = target.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {
                    "priority": 1,
                    "confidence": 0.30,
                    "theme": str(qobj.get("topic", "") or "open_question"),
                    "recommended_research": [],
                }
                target["metadata"] = metadata
            rec = metadata.get("recommended_research")
            if not isinstance(rec, list):
                rec = [rec] if rec not in (None, "", []) else []
            # Ensure question text is represented as a research topic.
            if q_text and q_text not in [str(x).strip() for x in rec]:
                rec.append(q_text)
                seeded_topics += 1
            metadata["recommended_research"] = rec
            decisions.append(
                {
                    "question": q_text,
                    "action": "matched_existing_item",
                    "matched_item_id": str(target.get("id", "") or ""),
                    "matched_key": matched_key or "",
                    "recommended_research_count": len(rec),
                }
            )
            continue

        new_item = _build_synthetic_open_question_item(qobj, idx)
        items.append(new_item)
        nk = _normalize_text_key(str(new_item.get("origin_text", "") or ""))
        if nk:
            by_origin_key[nk] = new_item
        injected += 1
        if str(new_item.get("origin_text", "") or "").strip():
            seeded_topics += 1
        decisions.append(
            {
                "question": q_text,
                "action": "injected_synthetic_item",
                "injected_item_id": str(new_item.get("id", "") or ""),
                "matched_key": "",
                "recommended_research_count": len(
                    new_item.get("metadata", {}).get("recommended_research", [])
                    if isinstance(new_item.get("metadata"), dict)
                    else []
                ),
            }
        )

    return ideas, {
        "remote_questions": len(remote_rows),
        "matched_items": matched,
        "injected_items": injected,
        "seeded_research_topics": seeded_topics,
        "decisions": decisions,
    }


def _cleanup_question_artifacts(project_id: str) -> None:
    """
    Remove consumed question artifacts after a successful Dream run.
    """
    base_dir = os.path.join(get_settings().memory_root, project_id)
    paths = [
        os.path.join(base_dir, "open_questions_consolidated.json"),
        os.path.join(base_dir, "open_questions.json"),
        os.path.join(base_dir, "open_questions.jsonl"),
    ]
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.info("[DREAM] Removed consumed questions artifact project=%s file=%s", project_id, os.path.basename(path))
        except Exception as e:
            logger.warning(
                "[DREAM] Failed removing questions artifact project=%s file=%s err=%s",
                project_id,
                os.path.basename(path),
                e,
            )


def write_dream_output(project_id: str, dream_data: dict, project_summary_text: str) -> None:
    """
    Write the final dream.json file for a project.

    This function performs no reasoning; it only serializes the Dream data structure
    returned by the Research Agent along with the project summary text.
    """
    try:
        def _capitalize_first_letter(text: str) -> str:
            """Capitalize the first non-whitespace character if it is a letter."""
            if not isinstance(text, str):
                return text
            leading_len = len(text) - len(text.lstrip())
            prefix = text[:leading_len]
            rest = text[leading_len:]
            if not rest:
                return text
            first = rest[0]
            if first.isalpha():
                rest = first.upper() + rest[1:]
            return prefix + rest

        base_dir = os.path.join(get_settings().memory_root, project_id)
        dream_path = os.path.join(base_dir, "dream.json")

        # Insert/overwrite project summary at top level.
        dream_data["project_summary"] = project_summary_text

        # Ensure date exists (MM/DD/YYYY using UTC, matching Idea Agent convention).
        date_val = dream_data.get("date")
        if not isinstance(date_val, str) or not date_val.strip():
            today = datetime.now(timezone.utc).strftime("%m/%d/%Y")
            dream_data["date"] = today

        # Ensure items exists and is a list.
        items = dream_data.get("items")
        if not isinstance(items, list):
            items = []
        # Normalize origin_text capitalization for display.
        normalized_items = []
        for it in items:
            if isinstance(it, dict):
                # Only adjust origin_text; leave other fields untouched.
                if "origin_text" in it:
                    it = {**it, "origin_text": _capitalize_first_letter(it.get("origin_text"))}
            normalized_items.append(it)
        existing_items: List[Any] = []
        if os.path.isfile(dream_path):
            existing_data = _read_json_file_safe(dream_path)
            if isinstance(existing_data, dict):
                pending_items = existing_data.get("items")
                if isinstance(pending_items, list):
                    existing_items = pending_items
                else:
                    logger.warning(
                        "[DREAM] Existing dream.json has invalid items; project=%s preserving_new_items_only",
                        project_id,
                    )
            else:
                logger.warning(
                    "[DREAM] Existing dream.json is invalid; project=%s preserving_new_items_only",
                    project_id,
                )
        dream_data["items"] = existing_items + normalized_items

        # Serialize to JSON and write to memory/{project_id}/dream.json.
        os.makedirs(base_dir, exist_ok=True)
        with open(dream_path, "w", encoding="utf-8", newline="\n") as df:
            json.dump(dream_data, df, ensure_ascii=False, indent=2)

        logger.info(
            "[DREAM] Dream output written successfully for project=%s pending_items=%s new_items=%s total_items=%s",
            project_id,
            len(existing_items),
            len(normalized_items),
            len(dream_data["items"]),
        )
    except Exception as e:
        # Log error but do not propagate.
        logger.error("Dream Writer failed for project=%s: %s", project_id, e, exc_info=True)


def dream(project_id: str) -> None:
    """
    Execute Dream cycle for a project after Sleep completes.

    This function processes questions and builds dream context synchronously.

    Args:
        project_id: Project identifier
    Returns:
        None (exceptions are logged but not raised)
    """
    try:
        settings = get_settings()
        if not settings.enable_dream:
            return
        t0 = time.monotonic()
        debug_ts = _dream_file_timestamp()
        logger.info("[DREAM] Starting dreaming for project=%s", project_id)
        try:
            consolidated_questions_path = os.path.join(get_settings().memory_root, project_id, "open_questions_consolidated.json")
            questions_input = _read_json_file_safe(consolidated_questions_path)
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "questions_in",
                    [
                        ("INPUT", json.dumps(questions_input or {"questions": []}, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing questions_in debug project=%s: %s", project_id, de)

            # Process deterministic consolidated questions synchronously and keep results in memory.
            questions_data = run_questions_agent(project_id)
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "questions_out",
                    [
                        ("OUTPUT", json.dumps(questions_data, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing questions_out debug project=%s: %s", project_id, de)

            # Build dream context after questions are processed and sleep_summary.md
            dream_context, project_summary_text = build_dream_context(project_id, questions_data)
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "dream_context",
                    [
                        ("INPUT", dream_context),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing dream_context debug project=%s: %s", project_id, de)

            # Run Idea Agent on the constructed dream context.
            ideas = run_idea_agent(project_id, dream_context)
            resolution_stats = _attach_source_resolution_to_items(ideas, questions_data)
            logger.info(
                "[DREAM][RESOLUTION] project=%s total_items=%s resolved_items=%s",
                project_id,
                resolution_stats.get("total_items", 0),
                resolution_stats.get("resolved_items", 0),
            )
            filter_stats = _filter_idea_items_to_known_questions(ideas, questions_data)
            logger.info(
                "[DREAM][IDEA_FILTER] project=%s before=%s after=%s dropped=%s",
                project_id,
                filter_stats.get("before", 0),
                filter_stats.get("after", 0),
                filter_stats.get("dropped", 0),
            )
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "idea_output",
                    [
                        ("OUTPUT", json.dumps(ideas, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing idea_output debug project=%s: %s", project_id, de)

            # Ensure remote-backed question research is represented in idea_data
            # so Research Agent can persist it into final dream.json.
            bridged_ideas, bridge_stats = _bridge_remote_questions_into_ideas(ideas, questions_data)
            logger.info(
                "[DREAM][BRIDGE] project=%s remote_questions=%s matched=%s injected=%s seeded_topics=%s",
                project_id,
                bridge_stats["remote_questions"],
                bridge_stats["matched_items"],
                bridge_stats["injected_items"],
                bridge_stats["seeded_research_topics"],
            )
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "bridge_report",
                    [
                        (
                            "DECISIONS",
                            json.dumps(
                                {
                                    "stats": {
                                        "remote_questions": bridge_stats.get("remote_questions", 0),
                                        "matched_items": bridge_stats.get("matched_items", 0),
                                        "injected_items": bridge_stats.get("injected_items", 0),
                                        "seeded_research_topics": bridge_stats.get("seeded_research_topics", 0),
                                    },
                                    "rows": bridge_stats.get("decisions", []),
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                        ),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing bridge_report debug project=%s: %s", project_id, de)

            research_plan_rows = _build_research_plan_rows(bridged_ideas)
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "research_plan",
                    [
                        ("INPUT", json.dumps(research_plan_rows, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing research_plan debug project=%s: %s", project_id, de)

            # Run Research Agent on the Idea Agent output, using the project summary text.
            dream_data = run_research_agent(
                project_id,
                bridged_ideas,
                project_summary_text,
                debug_ts=debug_ts,
            )
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "research_results",
                    [
                        ("OUTPUT", json.dumps(dream_data, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing research_results debug project=%s: %s", project_id, de)

            # Write dreaming-scoped debug artifact for research input/output.
            try:
                research_debug_body = (
                    f"# timestamp: {debug_ts}\n"
                    f"# project_id: {project_id}\n"
                    "\n"
                    "====== RESEARCH INPUT (JSON) ======\n"
                    f"{json.dumps(bridged_ideas, ensure_ascii=False, indent=2)}\n\n"
                    "====== RESEARCH OUTPUT (JSON) ======\n"
                    f"{json.dumps(dream_data, ensure_ascii=False, indent=2)}\n"
                )
                write_debug_file(project_id, f"dreaming/{debug_ts}_research.txt", research_debug_body)
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing dreaming research debug project=%s: %s", project_id, de)

            # Mirror the current debug_dream_summary.txt into dreaming/{timestamp}_dream_summary.txt.
            try:
                summary_debug_path = os.path.join(get_settings().memory_root, project_id, "debug", "debug_dream_summary.txt")
                if os.path.isfile(summary_debug_path):
                    with open(summary_debug_path, "r", encoding="utf-8", errors="ignore") as sf:
                        summary_debug_text = sf.read()
                    write_debug_file(project_id, f"dreaming/{debug_ts}_dream_summary.txt", summary_debug_text)
                else:
                    logger.info(
                        "[DREAM][DEBUG] debug_dream_summary.txt missing for project=%s; skipping dreaming summary mirror.",
                        project_id,
                    )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing dreaming summary debug project=%s: %s", project_id, de)

            # Serialize final Dream output to disk for downstream consumers (e.g., GUI).
            try:
                _write_dreaming_debug_txt(
                    project_id,
                    debug_ts,
                    "dream_write",
                    [
                        ("INPUT", json.dumps({"project_summary": project_summary_text}, ensure_ascii=False, indent=2)),
                        ("OUTPUT", json.dumps(dream_data, ensure_ascii=False, indent=2)),
                    ],
                )
            except Exception as de:
                logger.warning("[DREAM][DEBUG] Failed writing dream_write debug project=%s: %s", project_id, de)
            write_dream_output(project_id, dream_data, project_summary_text)

            # Clear consumed question artifacts to prevent duplicate re-answering next cycle.
            _cleanup_question_artifacts(project_id)

            # Currently, dream_data is kept in-memory for potential downstream use.
            _ = dream_data  # placeholder to avoid lints until consumed

            elapsed = time.monotonic() - t0
            logger.info("[DREAM] Project %s complete in duration=%.2fs", project_id, elapsed)
        except Exception as de:
            logger.error("project=%s %s", project_id, de, exc_info=True)
    except Exception as exc:
        logger.warning("[DREAM] Non-fatal dream cycle failure project=%s detail=%s", project_id, exc, exc_info=True)



