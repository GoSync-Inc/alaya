"""Tests for search service and rate limiter."""

import uuid

import pytest
from pydantic import ValidationError

from alayaos_core.schemas.search import EvidenceUnit, SearchRequest, SearchResponse


def test_search_request_validation():
    req = SearchRequest(query="test query")
    assert req.query == "test query"
    assert req.limit == 10


def test_search_request_empty_query_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_limit_bounds():
    with pytest.raises(ValidationError):
        SearchRequest(query="test", limit=0)
    with pytest.raises(ValidationError):
        SearchRequest(query="test", limit=100)


def test_search_request_max_query_length():
    with pytest.raises(ValidationError):
        SearchRequest(query="x" * 1001)


def test_evidence_unit_schema():
    unit = EvidenceUnit(
        source_type="entity",
        source_id=uuid.uuid4(),
        content="Test entity",
        score=0.85,
        channels=["fts", "entity_name"],
        entity_id=uuid.uuid4(),
        entity_name="Test",
    )
    assert unit.source_type == "entity"
    assert len(unit.channels) == 2


def test_search_response_schema():
    resp = SearchResponse(
        query="test",
        results=[],
        total=0,
        channels_used=["fts"],
        elapsed_ms=5,
    )
    assert resp.total == 0
    assert resp.elapsed_ms == 5


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    from alayaos_core.services.rate_limiter import RateLimiterService

    limiter = RateLimiterService(redis=None)
    allowed, retry = await limiter.check("test_key", 10, 60)
    assert allowed is True
    assert retry is None


def test_evidence_unit_channels_validation():
    unit = EvidenceUnit(
        source_type="claim",
        source_id=uuid.uuid4(),
        content="status: active",
        score=0.5,
        channels=["vector"],
        claim_id=uuid.uuid4(),
        confidence=0.9,
    )
    assert unit.confidence == 0.9
