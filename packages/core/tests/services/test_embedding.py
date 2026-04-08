"""Tests for embedding service and vector chunk repository."""

import pytest

from alayaos_core.services.embedding import FakeEmbeddingService


@pytest.mark.asyncio
async def test_fake_embedding_dimensions():
    service = FakeEmbeddingService(dimensions=1024)
    result = await service.embed_text("hello world")
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_fake_embedding_deterministic():
    service = FakeEmbeddingService(dimensions=1024)
    r1 = await service.embed_text("hello")
    r2 = await service.embed_text("hello")
    assert r1 == r2


@pytest.mark.asyncio
async def test_fake_embedding_different_texts():
    service = FakeEmbeddingService(dimensions=1024)
    r1 = await service.embed_text("hello")
    r2 = await service.embed_text("world")
    assert r1 != r2


@pytest.mark.asyncio
async def test_fake_embedding_batch():
    service = FakeEmbeddingService(dimensions=1024)
    results = await service.embed_texts(["hello", "world", "test"])
    assert len(results) == 3
    assert all(len(r) == 1024 for r in results)


@pytest.mark.asyncio
async def test_fake_embedding_values_in_range():
    service = FakeEmbeddingService(dimensions=1024)
    result = await service.embed_text("test input")
    assert all(-1.0 <= v <= 1.0 for v in result)
