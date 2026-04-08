"""Embedding service interface and FastEmbed adapter."""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

log = structlog.get_logger()


class EmbeddingServiceInterface(Protocol):
    """Protocol for embedding providers."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_text(self, text: str) -> list[float]: ...


class FastEmbedService:
    """ONNX-based embedding via FastEmbed. CPU-only, no PyTorch."""

    def __init__(self, model_name: str, dimensions: int) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = await asyncio.to_thread(lambda: list(model.embed(texts)))
        return [e.tolist() for e in embeddings]

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_texts([text])
        return results[0]


class FakeEmbeddingService:
    """Deterministic embedding service for tests."""

    def __init__(self, dimensions: int = 1024) -> None:
        self._dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._deterministic_vector(t) for t in texts]

    async def embed_text(self, text: str) -> list[float]:
        return self._deterministic_vector(text)

    def _deterministic_vector(self, text: str) -> list[float]:
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        return [((b % 200) - 100) / 100.0 for b in (h * ((self._dimensions // len(h)) + 1))[: self._dimensions]]
