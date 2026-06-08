"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Memory management for Syx AGI Chatbot Framework.

Implements per-project working memory deques mirrored to DB `ChatMessage`.
System (RAG) messages are not stored. Provides last_context_tokens per project for stats.
"""

import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from filelock import FileLock
from sqlmodel import select

from ..pruning.light_response_pruner import Pruner, PrunerConfig, PruneResult
from ..rag.daily_store import append_pair
from ..tagging.tagger import tag_pair
from ..utils.debug_utils import write_debug_file
from ..utils.logging import get_namespace
from ..utils.tokens import count_tokens
from .config import get_response_pruning_stage_config, get_settings
from .database import get_session
from .db_models import ChatMessage, Project

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRUNER_CACHE_KEY: Optional[tuple[Any, ...]] = None
_PRUNER_CACHE: Optional[Pruner] = None


def _resolve_response_pruning_rules_path(raw_path: str) -> Path:
    """Resolve the pruning rules path, trying CWD then the repo root.

    Absolute paths are returned as-is; relative paths prefer a match under the
    current working directory and fall back to the repository root.

    Args:
        raw_path: Configured rules path; empty values default to
            ``backend/app/config/rules.json``.

    Returns:
        The resolved ``Path`` to the rules file.
    """
    path = Path(str(raw_path or "backend/app/config/rules.json"))
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    return _REPO_ROOT / path


def _get_response_pruner(settings: Any) -> Pruner:
    """Return a cached ``Pruner`` keyed by the effective pruning configuration.

    The pruner is rebuilt only when any rules-path or pruning setting changes,
    avoiding repeated rule-file parsing on the hot path.

    Args:
        settings: Settings object supplying rules path, token caps, and the
            response-pruning tuning parameters that form the cache key.

    Returns:
        A configured ``Pruner`` instance (cached across calls with identical
        configuration).
    """
    global _PRUNER_CACHE
    global _PRUNER_CACHE_KEY

    rules_path = _resolve_response_pruning_rules_path(
        getattr(settings, "response_pruning_rules_path", "backend/app/config/rules.json")
    )
    stage_config = get_response_pruning_stage_config()
    cache_key = (
        str(rules_path),
        int(getattr(settings, "model_max_tokens", 128_000)),
        int(getattr(settings, "response_pruning_max_front_units", 3)),
        int(getattr(settings, "response_pruning_similarity_threshold", 90)),
        str(getattr(settings, "response_pruning_whitespace_mode", "compact_prose")),
        tuple(sorted(stage_config.items())),
    )

    if _PRUNER_CACHE is not None and _PRUNER_CACHE_KEY == cache_key:
        return _PRUNER_CACHE

    config = PrunerConfig(
        max_response_size=cache_key[1],
        max_front_units=cache_key[2],
        similarity_threshold=cache_key[3],
        whitespace_mode=cache_key[4],
        response_pruning=stage_config,
    )
    _PRUNER_CACHE = Pruner.from_file(rules_path, config=config, strip_comment_keys=True)
    _PRUNER_CACHE_KEY = cache_key
    return _PRUNER_CACHE


def _write_light_pruner_debug(
    *,
    project_id: str,
    original_response: str,
    pruned_response: str,
    result: Optional[PruneResult],
    error: Optional[Exception] = None,
) -> None:
    """Write a best-effort light-pruner debug dump for one assistant response.

    Args:
        project_id: Project the dump belongs to.
        original_response: Assistant text before pruning.
        pruned_response: Assistant text after pruning.
        result: Prune result whose stats are recorded, or None when pruning was
            skipped or failed.
        error: Exception captured during pruning, recorded in the dump header
            when present.
    """
    try:
        start_tokens = count_tokens(original_response)
        finished_tokens = count_tokens(pruned_response)
        tokens_saved = start_tokens - finished_tokens
        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        fname = f"{ts}_light_pruner.txt"
        body = (
            f"# timestamp: {ts}\n"
            f"# project_id: {project_id}\n"
            f"# success: {str(error is None).lower()}\n"
            f"# start_tokens: {start_tokens}\n"
            f"# finished_tokens: {finished_tokens}\n"
            f"# tokens_saved: {tokens_saved}\n"
        )
        if result is not None:
            body += (
                f"# changed: {str(bool(result.changed)).lower()}\n"
                f"# trimmed_side: {result.trimmed_side}\n"
                f"# front_units_removed: {result.front_units_removed}\n"
                f"# end_span_removed: {result.end_span_removed}\n"
                f"# blocked_by_safety: {str(bool(result.blocked_by_safety)).lower()}\n"
            )
        if error is not None:
            body += f"# error: {str(error)}\n"
        body += (
            "\n"
            "====== LIGHT PRUNER ORIGINAL RESPONSE ======\n"
            + (original_response or "")
            + "\n\n====== LIGHT PRUNER PRUNED RESPONSE ======\n"
            + (pruned_response or "")
            + "\n"
        )
        write_debug_file(project_id, f"prompts/{fname}", body)
    except Exception as exc:
        logger.warning(
            "[LIGHT_PRUNER] Failed writing debug dump project_id=%s detail=%s",
            project_id,
            exc,
        )


def _prune_assistant_for_tagger(
    *,
    project_id: str,
    assistant_text: str,
    settings: Any,
) -> str:
    """Prune an assistant response for tagging input, returning safe text.

    Honors the response-pruning enable flag and always returns the original
    text on failure so tagging can proceed without data loss.

    Args:
        project_id: Project whose response is being pruned.
        assistant_text: Raw assistant response to prune.
        settings: Settings object providing the response-pruning toggle and
            pruner configuration.

    Returns:
        The pruned response text, or the original text when pruning is disabled
        or fails.
    """
    original = str(assistant_text or "")
    try:
        if not bool(getattr(settings, "response_pruning_enabled", True)):
            start_tokens = count_tokens(original)
            logger.debug(
                "[LIGHT_PRUNER] project_id=%s enabled=false start_tokens=%s finished_tokens=%s tokens_saved=%s",
                project_id,
                start_tokens,
                start_tokens,
                0,
            )
            _write_light_pruner_debug(
                project_id=project_id,
                original_response=original,
                pruned_response=original,
                result=None,
            )
            return original

        result = _get_response_pruner(settings).prune(original)
        start_tokens = count_tokens(original)
        finished_tokens = count_tokens(result.pruned_text)
        logger.debug(
            "[LIGHT_PRUNER] project_id=%s changed=%s trimmed_side=%s start_tokens=%s finished_tokens=%s tokens_saved=%s",
            project_id,
            bool(result.changed),
            result.trimmed_side,
            start_tokens,
            finished_tokens,
            start_tokens - finished_tokens,
        )
        _write_light_pruner_debug(
            project_id=project_id,
            original_response=original,
            pruned_response=result.pruned_text,
            result=result,
        )
        return result.pruned_text
    except Exception as exc:
        start_tokens = count_tokens(original)
        logger.warning(
            "[LIGHT_PRUNER] Failed pruning assistant response; project_id=%s detail=%s",
            project_id,
            exc,
        )
        logger.debug(
            "[LIGHT_PRUNER] project_id=%s success=false start_tokens=%s finished_tokens=%s tokens_saved=%s",
            project_id,
            start_tokens,
            start_tokens,
            0,
        )
        _write_light_pruner_debug(
            project_id=project_id,
            original_response=original,
            pruned_response=original,
            result=None,
            error=exc,
        )
        return original


@dataclass
class _AssistantTagResult:
    """Result of tagging an assistant turn, carrying metadata for persistence.

    Attributes:
        tags_meta: Parsed tagger metadata dict (or None when tagging is skipped
            or fails). May include the private ``_pruned_assistant_text`` field.
        tags_meta_json: JSON serialization of ``tags_meta`` stored on the row
            (or None).
        semantic_handle: Semantic handle from the tagger (or None).
        question_candidates: Normalized open-question candidates.
        pruned_assistant_text: Pruned assistant text when pruning changed the
            content (used for roll-off), else None.
    """

    tags_meta: Optional[Dict[str, Any]] = None
    tags_meta_json: Optional[str] = None
    semantic_handle: Optional[str] = None
    question_candidates: List[Dict[str, str]] = field(default_factory=list)
    pruned_assistant_text: Optional[str] = None


class MemoryManager:
    """Per-project working memory mirrored with the database.

    Owns the in-process per-project message deques used to build conversation
    history and to drive roll-off, keeping them consistent with the persisted
    ``ChatMessage`` rows. Responsibilities include appending user/assistant
    turns, tagging assistant turns, rolling the oldest pair into Daily memory
    when a project's active window is full, and tracking the last context-token
    estimate per project.

    Invariants:
        - The deque for a project is bounded by the configured active-window
          size; exceeding it triggers roll-off of the oldest pair.
        - Daily persistence is treated as a durability invariant: failures to
          append to Daily are logged rather than silently dropped.
    """

    def __init__(self):
        self.project_deques: Dict[str, Deque[Dict[str, Any]]] = {}
        self.last_context_tokens_per_project: Dict[str, int] = {}
        s = get_settings()
        self.limit = s.chat_history_limit
        self.pair_limit = s.chat_history_limit_pairs
        logger.info("Memory manager initialized (persistent mode)")

    @staticmethod
    def _normalize_question_candidates(value: Any) -> List[Dict[str, str]]:
        """Normalize tagger question output into validated candidate dicts.

        Drops malformed entries and entries without question text, and coerces
        any unrecognized resolution to ``ignore``.

        Args:
            value: Raw tagger ``questions`` value, expected to be a list of
                dicts; non-list input yields an empty result.

        Returns:
            A list of ``{question, topic, resolution}`` dicts with validated
            resolution values.
        """
        allowed = {"ignore", "answer_local", "answer_remote"}
        out: List[Dict[str, str]] = []
        if not isinstance(value, list):
            return out
        for item in value:
            if not isinstance(item, dict):
                continue
            q_text = str(item.get("question", "") or "").strip()
            q_topic = str(item.get("topic", "") or "").strip()
            q_resolution = str(item.get("resolution", "") or "").strip().lower()
            if not q_text:
                continue
            if q_resolution not in allowed:
                q_resolution = "ignore"
            out.append({"question": q_text, "topic": q_topic, "resolution": q_resolution})
        return out

    def _append_open_questions_artifact(
        self,
        *,
        project_id: str,
        assistant_message_id: Optional[int],
        user_message_id: Optional[int],
        namespace: str,
        semantic_handle: Optional[str],
        questions: List[Dict[str, str]],
    ) -> None:
        """Append tagger-derived open questions to ``open_questions.jsonl``.

        Writes one JSON line per question under a per-project file lock. This is
        best-effort: failures are logged and never interrupt the chat flow.

        Args:
            project_id: Project the questions belong to.
            assistant_message_id: DB id of the assistant message, or None.
            user_message_id: DB id of the source user message, or None.
            namespace: Namespace recorded with each question; defaults to
                ``other`` when empty.
            semantic_handle: Semantic handle recorded with each question, if
                available.
            questions: Validated question candidates to append; a no-op when
                empty.
        """
        if not questions:
            return
        try:
            base_dir = os.path.join(get_settings().memory_root, project_id)
            os.makedirs(base_dir, exist_ok=True)
            artifact_path = os.path.join(base_dir, "open_questions.jsonl")
            state_dir = os.path.join(base_dir, "state")
            os.makedirs(state_dir, exist_ok=True)
            lock_path = os.path.join(state_dir, "open_questions.lock")
            legacy_lock_path = os.path.join(base_dir, "open_questions.lock")
            if os.path.isfile(legacy_lock_path) and not os.path.exists(lock_path):
                try:
                    os.replace(legacy_lock_path, lock_path)
                except OSError as exc:
                    logger.warning(
                        "memory questions lock migration failed project_id=%s detail=%s",
                        project_id,
                        exc,
                    )
            pair_id: Optional[str] = None
            if isinstance(user_message_id, int) and isinstance(assistant_message_id, int):
                pair_id = f"{user_message_id}:{assistant_message_id}"
            with FileLock(lock_path):
                with open(artifact_path, "a", encoding="utf-8", newline="\n") as f:
                    for idx, q in enumerate(questions, start=1):
                        payload: Dict[str, Any] = {
                            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "source": "tagger_ingest",
                            "project_id": project_id,
                            "assistant_message_id": assistant_message_id,
                            "user_message_id": user_message_id,
                            "pair_id": pair_id,
                            "namespace": (namespace or "other"),
                            "semantic_handle": (semantic_handle or ""),
                            "question_index": int(idx),
                            "question": q.get("question", ""),
                            "topic": q.get("topic", ""),
                            "resolution": q.get("resolution", "ignore"),
                        }
                        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(
                "[QUESTIONS][ARTIFACT] Failed writing open_questions.jsonl project=%s: %s",
                project_id,
                e,
            )

    def _ensure_loaded(self, project_id: str) -> None:
        """Lazily hydrate the project's working-memory deque from the DB.

        Loads the most recent messages (newest-first, then reversed to
        chronological order) and trims unpaired edge messages. No-op if the
        project deque is already loaded.

        Args:
            project_id: Project whose working memory to load.
        """
        if project_id in self.project_deques:
            return
        # Use a deque sized to avoid dropping messages before pair-based pruning runs.
        # Ensure capacity for at least 2*pair_limit messages.
        maxlen = max(self.pair_limit * 2, self.limit)
        dq: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        try:
            with get_session() as session:
                rows = session.exec(
                    select(ChatMessage)
                    .where(ChatMessage.project_id == project_id)
                    .order_by(ChatMessage.created_at.desc())
                ).all()
                rows = rows[:maxlen]
                for r in reversed(rows):
                    dq.append(
                        {
                            "id": r.id,
                            "role": r.role,
                            "content": r.content,
                            "created_at": r.created_at,
                            "forget": getattr(r, "forget", False),
                            "namespace": getattr(r, "namespace", None),
                            "keep": getattr(r, "keep", False),
                            "tags_meta_json": getattr(r, "tags_meta_json", None),
                            "semantic_handle": getattr(r, "semantic_handle", None),
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to load history for {project_id}: {e}")
        # Cleanup unpaired trailing user and orphan leading assistant per current spec.
        self._cleanup_unpaired_edges(project_id, dq)
        self.project_deques[project_id] = dq

    def get_project_history(
        self, project_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return the project's working-memory messages, optionally tail-limited.

        Args:
            project_id: Project whose history to return.
            limit: If set, return only the most recent ``limit`` messages.

        Returns:
            The project's message dicts in chronological order, tail-limited
            when ``limit`` is provided.
        """
        self._ensure_loaded(project_id)
        data = list(self.project_deques.get(project_id, deque()))
        return data if limit is None else data[-limit:]

    def append_user_message(self, project_id: str, content: str) -> None:
        """Persist a user message and append it to working memory.

        Pruning to the pair limit runs after the append. No-op when
        ``project_id`` is empty.

        Args:
            project_id: Project receiving the message.
            content: User message text to persist.
        """
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            msg = ChatMessage(project_id=project_id, role="user", content=content, created_at=now)
            session.add(msg)
            session.commit()
            session.refresh(msg)
        self.project_deques[project_id].append(
            {
                "id": msg.id,
                "role": "user",
                "content": content,
                "created_at": now,
            }
        )
        self.prune_to_limit(project_id)

    def append_assistant_message(
        self,
        project_id: str,
        content: str,
        namespace: Optional[str] = None,
        *,
        user_text_for_tagging: Optional[str] = None,
        previous_pair_text_for_tagging: Optional[str] = None,
        forget: bool = False,
        skip_tagger: bool = False,
    ) -> None:
        """Persist an assistant message, run tagging, and update working memory.

        Unless ``skip_tagger`` is set (or no user text is supplied), the
        assistant text is pruned and tagged; the resulting metadata is stored on
        the message row and the project's ``last_semantic_handle``. Open
        questions are appended as an artifact and the deque is pruned to limit.

        Args:
            project_id: Project receiving the message.
            content: Assistant response text.
            namespace: Namespace override; defaults to the current request
                namespace or ``other``.
            user_text_for_tagging: User turn used as tagging anchor; tagging is
                skipped when None.
            previous_pair_text_for_tagging: Prior pair text used as tagging
                context.
            forget: If True, this pair is excluded from daily/LTM roll-off.
            skip_tagger: If True, bypass tagging entirely.
        """
        if not project_id:
            return
        self._ensure_loaded(project_id)
        now = datetime.now(timezone.utc)
        ns = (namespace or get_namespace() or "other").lower()
        source_user_message_id = self._find_source_user_message_id(project_id)
        tag_result = self._tag_assistant_pair(
            project_id=project_id,
            content=content,
            user_text_for_tagging=user_text_for_tagging,
            previous_pair_text_for_tagging=previous_pair_text_for_tagging,
            skip_tagger=skip_tagger,
        )
        msg_id = self._persist_assistant_row(
            project_id=project_id,
            content=content,
            now=now,
            forget=bool(forget),
            ns=ns,
            tags_meta_json=tag_result.tags_meta_json,
            semantic_handle=tag_result.semantic_handle,
        )
        self.project_deques[project_id].append(
            {
                "id": msg_id,
                "role": "assistant",
                "content": content,
                "created_at": now,
                "forget": bool(forget),
                "namespace": ns,
                "keep": False,
                "tags_meta_json": tag_result.tags_meta_json,
                "semantic_handle": tag_result.semantic_handle,
                "pruned_content": tag_result.pruned_assistant_text,
            }
        )
        self._append_open_questions_artifact(
            project_id=project_id,
            assistant_message_id=(int(msg_id) if isinstance(msg_id, int) else None),
            user_message_id=source_user_message_id,
            namespace=ns,
            semantic_handle=(
                tag_result.semantic_handle if isinstance(tag_result.semantic_handle, str) else None
            ),
            questions=tag_result.question_candidates,
        )
        self.prune_to_limit(project_id)

    def _find_source_user_message_id(self, project_id: str) -> Optional[int]:
        """Return the id of the user message immediately preceding this turn.

        Inspects the tail of the working-memory deque; the assistant turn being
        appended is anchored to that user message for open-question provenance.

        Args:
            project_id: Project whose deque tail is inspected.

        Returns:
            The trailing user message id, or None when the tail is not a user
            message or the lookup fails.
        """
        try:
            dq = self.project_deques.get(project_id)
            if dq:
                last = dq[-1]
                if isinstance(last, dict) and (last.get("role") == "user"):
                    uid = last.get("id")
                    return int(uid) if isinstance(uid, int) else None
        except Exception as exc:
            logger.warning(
                "append_assistant_message source user lookup failed; project_id=%s detail=%s",
                project_id,
                exc,
            )
        return None

    def _tag_assistant_pair(
        self,
        *,
        project_id: str,
        content: str,
        user_text_for_tagging: Optional[str],
        previous_pair_text_for_tagging: Optional[str],
        skip_tagger: bool,
    ) -> _AssistantTagResult:
        """Prune and tag the assistant turn, returning persistence metadata.

        No-ops (returns an empty result) when ``skip_tagger`` is set or no user
        anchor text is supplied. Uses the immediately previous active pair as
        the tagging context anchor. Tagger/serialization failures are logged and
        downgraded to empty metadata so the message still persists.

        Args:
            project_id: Project being tagged.
            content: Raw assistant response text.
            user_text_for_tagging: User turn used as the tagging anchor; tagging
                is skipped when None.
            previous_pair_text_for_tagging: Prior pair text used as context.
            skip_tagger: When True, bypass tagging entirely.

        Returns:
            An ``_AssistantTagResult`` with tags metadata, its JSON form, the
            semantic handle, normalized question candidates, and any pruned
            assistant text.
        """
        result = _AssistantTagResult()
        # Tag immediately after assistant reply using the immediately previous active pair as context anchor.
        try:
            if (not bool(skip_tagger)) and (user_text_for_tagging is not None):
                settings = get_settings()
                assistant_text_for_tagging = _prune_assistant_for_tagger(
                    project_id=project_id,
                    assistant_text=content,
                    settings=settings,
                )
                if assistant_text_for_tagging != str(content or ""):
                    result.pruned_assistant_text = assistant_text_for_tagging
                tagged = tag_pair(
                    user_text_for_tagging,
                    assistant_text_for_tagging,
                    previous_pair_text=previous_pair_text_for_tagging,
                    project_id=project_id,
                )
                if isinstance(tagged, dict):
                    tags_meta = {
                        "topics": tagged.get("topics", "") or "",
                        "intent": tagged.get("intent", "") or "",
                        "type": tagged.get("type", "") or "",
                        # semantic_handle is required but may be empty; store None only if missing.
                        "semantic_handle": tagged.get("semantic_handle", None),
                    }
                    if result.pruned_assistant_text is not None:
                        # Private rolloff-only field: daily/LTM should carry pruned assistant text.
                        tags_meta["_pruned_assistant_text"] = result.pruned_assistant_text
                    result.tags_meta = tags_meta
                    result.question_candidates = self._normalize_question_candidates(
                        tagged.get("questions")
                    )
                    result.semantic_handle = tags_meta.get("semantic_handle", None)
                    try:
                        result.tags_meta_json = json.dumps(tags_meta, ensure_ascii=False)
                    except Exception as exc:
                        logger.warning(
                            "append_assistant_message tag metadata serialization failed; project_id=%s detail=%s",
                            project_id,
                            exc,
                        )
                        result.tags_meta_json = None
        except Exception as exc:
            logger.warning(
                "append_assistant_message tagging failed; project_id=%s detail=%s",
                project_id,
                exc,
            )
            result.tags_meta = None
            result.tags_meta_json = None
            result.semantic_handle = None
        return result

    def _persist_assistant_row(
        self,
        *,
        project_id: str,
        content: str,
        now: datetime,
        forget: bool,
        ns: str,
        tags_meta_json: Optional[str],
        semantic_handle: Optional[str],
    ) -> Optional[int]:
        """Insert the assistant ``ChatMessage`` and mirror the semantic handle.

        Persists the assistant row and, when a non-empty semantic handle is
        present, updates ``Project.last_semantic_handle`` so it survives the
        sleep flush (which wipes ``ChatMessage``).

        Args:
            project_id: Project receiving the message.
            content: Assistant response text.
            now: Creation timestamp.
            forget: Whether the pair is excluded from roll-off.
            ns: Resolved namespace.
            tags_meta_json: Serialized tagger metadata (or None).
            semantic_handle: Semantic handle to store (or None).

        Returns:
            The new message id assigned by the database.
        """
        with get_session() as session:
            msg = ChatMessage(
                project_id=project_id,
                role="assistant",
                content=content,
                created_at=now,
                forget=bool(forget),
                namespace=ns,
                keep=False,
                tags_meta_json=tags_meta_json,
                semantic_handle=semantic_handle,
            )
            session.add(msg)
            # Persist last non-empty semantic handle across sleep flush (ChatMessage is wiped).
            try:
                if isinstance(semantic_handle, str) and semantic_handle.strip():
                    p = session.get(Project, project_id)
                    if p is not None:
                        p.last_semantic_handle = semantic_handle.strip()
                        session.add(p)
            except Exception as exc:
                logger.warning(
                    "append_assistant_message failed updating project semantic handle; project_id=%s detail=%s",
                    project_id,
                    exc,
                )
            session.commit()
            session.refresh(msg)
            return msg.id

    def prune_to_limit(self, project_id: str) -> None:
        """Roll off oldest complete pairs until within the pair limit.

        Args:
            project_id: Project whose working memory to prune.
        """
        self._ensure_loaded(project_id)
        dq = self.project_deques[project_id]
        # If we have at least one complete pair at the head, and pair_limit exceeded, roll off the oldest pair
        while self._pair_count(dq) > self.pair_limit:
            self._rolloff_oldest_pair(project_id, dq)

    def _pair_count(self, dq: Deque[Dict[str, Any]]) -> int:
        """Count adjacent user→assistant message pairs in deque order.

        Args:
            dq: Working-memory deque of message dicts to scan.

        Returns:
            The number of complete user→assistant pairs found.
        """
        count = 0
        i = 0
        n = len(dq)
        while i + 1 < n:
            if dq[i].get("role") == "user" and dq[i + 1].get("role") == "assistant":
                count += 1
                i += 2
            else:
                i += 1
        return count

    def _rolloff_oldest_pair(self, project_id: str, dq: Deque[Dict[str, Any]]) -> None:
        """Evict the oldest pair, appending it to daily RAG before DB deletion.

        Stray non-pair messages at the head are deleted first. The evicted pair
        is appended to the daily store (unless forgotten or daily is disabled),
        reusing stored tagger metadata and pruned text, then both rows are
        removed from the database. Append failures are logged; eviction still
        proceeds per spec.

        Args:
            project_id: Project whose oldest pair is being evicted.
            dq: Working-memory deque to mutate in place.
        """
        # Ensure the first two form a pair; if not, clean or skip until a pair is found
        while len(dq) >= 2:
            first, second = dq[0], dq[1]
            if first.get("role") == "user" and second.get("role") == "assistant":
                break
            # Delete stray message from DB and drop it
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[0].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting stray message {dq[0].get('id')}: {e}")
            dq.popleft()
        if len(dq) < 2:
            return
        user_msg = dq.popleft()
        asst_msg = dq.popleft()
        self._append_pair_to_daily(project_id, user_msg, asst_msg)
        self._delete_pair_rows(user_msg, asst_msg)

    def _append_pair_to_daily(
        self,
        project_id: str,
        user_msg: Dict[str, Any],
        asst_msg: Dict[str, Any],
    ) -> None:
        """Append an evicted pair to the daily store, reusing stored metadata.

        Skips the append when the pair is forgotten or Daily RAG is disabled.
        Roll-off does NOT re-run the tagger; it reuses metadata stored on the
        assistant row, preferring pruned assistant text (from the deque or the
        stored ``_pruned_assistant_text``) and prepending a tags block to the
        embedded text. Append failures are logged; eviction still proceeds.

        Args:
            project_id: Project whose pair is being rolled off.
            user_msg: Evicted user message dict.
            asst_msg: Evicted assistant message dict (source of metadata).
        """
        user_text = user_msg.get("content") or ""
        # Append to daily if enabled and not forgotten; on any error we still drop per spec
        try:
            if bool(asst_msg.get("forget")):
                logger.info(
                    "[FORGET] Skipped pair (forget flag set) user_id=%s assistant_id=%s",
                    str(user_msg.get("id")),
                    str(asst_msg.get("id")),
                )
            elif self._is_daily_enabled(project_id):
                ns = (asst_msg.get("namespace") or get_namespace() or "other").lower()
                keep = bool(asst_msg.get("keep"))
                # Roll-off does NOT call the tagger. It reuses metadata stored on the assistant row.
                tags_meta = None
                tags_meta_json = asst_msg.get("tags_meta_json")
                if isinstance(tags_meta_json, str) and tags_meta_json.strip():
                    try:
                        parsed = json.loads(tags_meta_json)
                        if isinstance(parsed, dict):
                            tags_meta = parsed
                    except Exception:
                        tags_meta = None
                pruned_from_meta = None
                if isinstance(tags_meta, dict):
                    pruned_candidate = tags_meta.get("_pruned_assistant_text")
                    if isinstance(pruned_candidate, str) and pruned_candidate.strip():
                        pruned_from_meta = pruned_candidate
                pruned_from_deque = asst_msg.get("pruned_content")
                asst_text = (
                    pruned_from_deque
                    if isinstance(pruned_from_deque, str) and pruned_from_deque.strip()
                    else (
                        pruned_from_meta
                        if isinstance(pruned_from_meta, str) and pruned_from_meta.strip()
                        else asst_msg.get("content") or ""
                    )
                )
                pair_text = f"User: {user_text}\nAssistant: {asst_text}"
                tokens = int(count_tokens(pair_text))
                logger.debug(
                    "[ROLLOFF] project_id=%s user_id=%s assistant_id=%s tokens_approx=%s pruned_for_daily=%s",
                    project_id,
                    str(user_msg.get("id")),
                    str(asst_msg.get("id")),
                    str(tokens),
                    str(asst_text != (asst_msg.get("content") or "")).lower(),
                )
                tags_block = ""
                if isinstance(tags_meta, dict):
                    try:
                        topics = str(tags_meta.get("topics", "") or "")
                        intent = str(tags_meta.get("intent", "") or "")
                        tag_type = str(tags_meta.get("type", "") or "")
                        semantic_handle = tags_meta.get("semantic_handle", None)
                        lines = [f"#topics: {topics}", f"#intent: {intent}", f"#type: {tag_type}"]
                        if semantic_handle is not None:
                            lines.append(
                                f"#semantic_handle: {str(semantic_handle) if semantic_handle is not None else ''}"
                            )
                        tags_block = "\n".join(lines) + "\n"
                    except Exception:
                        tags_block = ""
                embed_text = (tags_block + pair_text) if tags_block else pair_text
                append_pair(
                    project_id,
                    pair_text,
                    int(user_msg.get("id")),
                    int(asst_msg.get("id")),
                    int(tokens),
                    namespace=ns,
                    keep=keep,
                    embed_override=embed_text,
                    tags_meta={
                        key: value
                        for key, value in dict(tags_meta or {}).items()
                        if not str(key).startswith("_")
                    },
                )
            else:
                logger.info(
                    "[DailyRAG] Skipping daily append (disabled for project=%s)", project_id
                )
        except Exception as e:
            logger.error(f"DailyRAG rolloff append failed: {e}")

    def _delete_pair_rows(self, user_msg: Dict[str, Any], asst_msg: Dict[str, Any]) -> None:
        """Delete the evicted user/assistant rows from the database.

        Args:
            user_msg: Evicted user message dict (provides the row id).
            asst_msg: Evicted assistant message dict (provides the row id).
        """
        try:
            with get_session() as session:
                for mid in (user_msg.get("id"), asst_msg.get("id")):
                    row = session.get(ChatMessage, mid)
                    if row:
                        session.delete(row)
                session.commit()
        except Exception as e:
            logger.error(f"Failed deleting rolled-off DB rows: {e}")

    def _cleanup_unpaired_edges(self, project_id: str, dq: Deque[Dict[str, Any]]) -> None:
        """Delete orphan leading assistant messages and trailing unpaired user messages from DB and deque.

        Args:
            project_id: Project being cleaned (used for logging context).
            dq: Working-memory deque to trim in place.
        """
        # Clean orphan assistants at the head
        while len(dq) and dq[0].get("role") != "user":
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[0].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting orphan assistant {dq[0].get('id')}: {e}")
            dq.popleft()
        # Clean trailing unpaired user at the tail
        while len(dq) and dq[-1].get("role") != "assistant":
            try:
                with get_session() as session:
                    row = session.get(ChatMessage, dq[-1].get("id"))
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed deleting trailing unpaired message {dq[-1].get('id')}: {e}")
            dq.pop()

    def _is_daily_enabled(self, project_id: str) -> bool:
        """Return the project's Daily RAG flag, defaulting to True on error.

        Args:
            project_id: Project whose Daily RAG setting to read.

        Returns:
            The project's ``daily_rag_enabled`` flag; True when the project is
            missing or the lookup fails.
        """
        try:
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is None:
                    return True
                return bool(p.daily_rag_enabled)
        except Exception as e:
            logger.warning(
                "Failed to read project daily flag for %s: %s; defaulting to True", project_id, e
            )
            return True

    def get_active_pair_count(self, project_id: str) -> int:
        """Return the number of complete pairs in the project's working memory.

        Args:
            project_id: Project whose pair count to return.

        Returns:
            The count of complete user→assistant pairs currently in memory.
        """
        self._ensure_loaded(project_id)
        dq = self.project_deques.get(project_id) or deque()
        return self._pair_count(dq)

    def set_last_context_tokens(self, project_id: str, tokens: int) -> None:
        """Record the most recent prompt-context token count for the project.

        Args:
            project_id: Project to update.
            tokens: Token count to store; clamped to be non-negative.
        """
        self.last_context_tokens_per_project[project_id] = max(0, int(tokens))

    def get_last_context_tokens(self, project_id: str) -> int:
        """Return the last recorded prompt-context token count (0 if unset).

        Args:
            project_id: Project whose token count to return.

        Returns:
            The last recorded prompt-context token count, or 0 when none was
            recorded.
        """
        return int(self.last_context_tokens_per_project.get(project_id, 0))

    def get_conversation_history(
        self, conversation_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return an empty list. Deprecated: project-scoped history is used.

        Args:
            conversation_id: Ignored; retained for backward compatibility.
            limit: Ignored; retained for backward compatibility.

        Returns:
            An empty list.
        """
        # Deprecated (project-scoped history is used instead).
        return []

    def search_memory(
        self, query: str, conversation_id: Optional[str] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search through stored memories (RAG functionality).

        Args:
            query: Search query
            conversation_id: Optional conversation to search within
            limit: Maximum number of results

        Returns:
            List of relevant memories
        """
        # TODO: Implement FAISS-based search.
        logger.info(f"Memory search requested: '{query}' (stub - not yet implemented)")

        return [
            {
                "content": f"Memory search for '{query}' not yet implemented",
                "relevance_score": 0.0,
                "source": "stub",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

    def cleanup_old_memories(
        self, retention_days: int = 30, conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clean up old memories (memory pruning).

        Args:
            retention_days: Number of days to retain memories
            conversation_id: Optional specific conversation to clean

        Returns:
            Cleanup statistics
        """
        # TODO: Implement memory pruning.
        logger.info("Memory cleanup requested (stub - not yet implemented)")

        return {
            "items_cleaned": 0,
            "memory_usage_before": "0MB",
            "memory_usage_after": "0MB",
            "retention_days": retention_days,
            "status": "stub_mode",
        }

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics.

        Returns:
            A dict with total conversation/message counts, the memory mode, and
            a ``features_available`` map of capability flags.
        """
        total_projects = len(self.project_deques)
        total_messages = sum(len(dq) for dq in self.project_deques.values())
        return {
            "total_conversations": total_projects,
            "total_messages": total_messages,
            "memory_mode": "persistent",
            "features_available": {
                "rag_search": False,
                "memory_pruning": False,
                "conversation_storage": True,
            },
        }


# Global instances
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Get the global memory manager instance.

    Returns:
        The process-wide ``MemoryManager`` singleton, created on first use.
    """
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


# Convenience functions


def store_conversation(
    conversation_id: str, message: str, response: str, metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Store a conversation message.

    Args:
        conversation_id: Conversation the exchange belongs to.
        message: User message text.
        response: Assistant response text.
        metadata: Optional metadata to associate with the stored message.

    Returns:
        True if the message was stored successfully.
    """
    manager = get_memory_manager()
    return manager.store_message(conversation_id, message, response, metadata)


def set_last_context_tokens(project_id: str, tokens: int) -> None:
    """Record the project's last prompt-context token count via the manager.

    Args:
        project_id: Project to update.
        tokens: Token count to store.
    """
    manager = get_memory_manager()
    manager.set_last_context_tokens(project_id, tokens)


def get_last_context_tokens(project_id: str) -> int:
    """Return the project's last prompt-context token count via the manager.

    Args:
        project_id: Project whose token count to return.

    Returns:
        The last recorded prompt-context token count, or 0 when unset.
    """
    manager = get_memory_manager()
    return manager.get_last_context_tokens(project_id)


def search_conversation_memory(
    query: str, conversation_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search conversation memory.

    Args:
        query: Search query text.
        conversation_id: Optional conversation to scope the search.

    Returns:
        A list of relevant memory result dicts (currently a stub result).
    """
    manager = get_memory_manager()
    return manager.search_memory(query, conversation_id)
