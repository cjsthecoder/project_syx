"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
SentenceTransformers embedding provider implementation.
"""


import logging
from typing import List, Optional

from sentence_transformers import SentenceTransformer

from ...core.config import get_active_embedding_model, get_settings
from ..base import EmbedResult

logger = logging.getLogger(__name__)


class SentenceTransformersEmbeddingProvider:
    def __init__(self) -> None:
        self._model_cache: dict[str, SentenceTransformer] = {}
        # Fail fast when sentence_transformers is the active provider.
        self._get_model(get_active_embedding_model())

    def _get_model(self, model_id: Optional[str] = None) -> SentenceTransformer:
        use_model = str(model_id or get_active_embedding_model()).strip()
        cached = self._model_cache.get(use_model)
        if cached is not None:
            return cached
        logger.info("Loading sentence-transformers model id=%s", use_model)
        model = SentenceTransformer(use_model)
        self._model_cache[use_model] = model
        logger.info("Loaded sentence-transformers model id=%s", use_model)
        return model

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        retries: int = 2,
        rate_limit_retries: int = 10,
    ) -> EmbedResult:
        del retries
        del rate_limit_retries
        settings = get_settings()
        clean = [t if isinstance(t, str) else "" for t in (texts or [])]
        if not clean:
            use_model = model or get_active_embedding_model()
            return EmbedResult(vectors=[], model=str(use_model))
        use_model = str(model or get_active_embedding_model()).strip()
        try:
            encoder = self._get_model(use_model)
            vectors_np = encoder.encode(
                clean,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = vectors_np.tolist()
            return EmbedResult(vectors=vectors, model=use_model)
        except Exception as exc:
            raise RuntimeError(
                "sentence-transformers embedding failed "
                f"model={use_model} provider={settings.embedding_provider}: {exc}"
            ) from exc

    def embed_query(self, text: str, *, model: Optional[str] = None) -> List[float]:
        res = self.embed([text or ""], model=model)
        return res.vectors[0] if res.vectors else []
