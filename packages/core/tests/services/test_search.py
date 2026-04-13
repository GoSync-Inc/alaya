"""Tests for search service and rate limiter."""

import uuid
from unittest.mock import AsyncMock, MagicMock

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
async def test_rate_limiter_fails_closed_without_redis():
    """RUN5.05: rate limiter must fail closed when Redis is unavailable."""
    from alayaos_core.services.rate_limiter import RateLimiterService

    limiter = RateLimiterService(redis=None)
    decision = await limiter.check("test_key", 10, 60)
    assert decision.allowed is False
    assert decision.backend_available is False


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


# ---------------------------------------------------------------------------
# RRF fusion key consistency (RUN4.04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rrf_fusion_same_entity_vector_and_fts_merges_to_single_result():
    """Vector and FTS channel results for the same entity must merge into one
    RRF entry (not two duplicates) when both channels return the same
    source_type/source_id key."""
    from alayaos_core.services import search as search_mod

    entity_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    # Vector channel: must return entity's own ID as source_id (not chunk UUID)
    vector_row = {
        "source_type": "entity",
        "source_id": entity_id,  # should be the entity UUID
        "content": "Alice: CEO of Acme",
        "entity_id": entity_id,
        "entity_name": None,
        "claim_id": None,
    }
    # FTS channel: returns entity UUID as source_id
    fts_row = {
        "source_type": "entity",
        "source_id": entity_id,
        "content": "Alice: CEO of Acme",
        "entity_id": entity_id,
        "entity_name": "Alice",
        "claim_id": None,
    }

    mock_session = AsyncMock()
    mock_embedding_service = AsyncMock()
    mock_embedding_service.embed_text = AsyncMock(return_value=[0.1] * 768)

    # Patch channel helpers and feature flag
    search_mod_patches = {
        "_vector_search": AsyncMock(return_value=[vector_row]),
        "_fts_search": AsyncMock(return_value=[fts_row]),
        "_entity_name_search": AsyncMock(return_value=[]),
    }

    original_vector = search_mod._vector_search
    original_fts = search_mod._fts_search
    original_name = search_mod._entity_name_search

    search_mod._vector_search = search_mod_patches["_vector_search"]
    search_mod._fts_search = search_mod_patches["_fts_search"]
    search_mod._entity_name_search = search_mod_patches["_entity_name_search"]

    # Patch Settings so vector search is enabled
    original_settings = search_mod.Settings

    class _FakeSettings:
        SEARCH_RRF_K = 60
        FEATURE_FLAG_VECTOR_SEARCH = True
        SEARCH_HNSW_EF_SEARCH = 100

    search_mod.Settings = _FakeSettings  # type: ignore[assignment]

    try:
        response = await search_mod.hybrid_search(
            session=mock_session,
            query="Alice",
            workspace_id=workspace_id,
            embedding_service=mock_embedding_service,
            limit=10,
        )
    finally:
        search_mod._vector_search = original_vector
        search_mod._fts_search = original_fts
        search_mod._entity_name_search = original_name
        search_mod.Settings = original_settings

    # The same entity must NOT appear twice — it must be merged into one result
    assert len(response.results) == 1, (
        f"Expected 1 merged result, got {len(response.results)}. "
        "Vector and FTS returned same entity UUID but produced duplicate keys."
    )
    result = response.results[0]
    assert result.source_id == entity_id
    # Score should reflect contribution from both channels (> score from one channel alone)
    single_channel_score = round(1.0 / (60 + 1), 6)
    assert result.score > single_channel_score, (
        f"Score {result.score} should be > {single_channel_score} (two channels merged)"
    )
    assert "vector" in result.channels
    assert "fts" in result.channels


# ---------------------------------------------------------------------------
# entity_types filter (RUN4.02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_types_filter_excludes_non_matching_types():
    """When entity_types=['person'] is provided, entities of other types must
    be excluded from the results."""
    from alayaos_core.services import search as search_mod

    person_id = uuid.uuid4()
    project_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    person_row = {
        "source_type": "entity",
        "source_id": person_id,
        "content": "Alice: engineer",
        "entity_id": person_id,
        "entity_name": "Alice",
        "claim_id": None,
    }
    project_row = {
        "source_type": "entity",
        "source_id": project_id,
        "content": "Orion: big project",
        "entity_id": project_id,
        "entity_name": "Orion",
        "claim_id": None,
    }

    original_vector = search_mod._vector_search
    original_fts = search_mod._fts_search
    original_name = search_mod._entity_name_search
    original_settings = search_mod.Settings

    class _FakeSettings:
        SEARCH_RRF_K = 60
        FEATURE_FLAG_VECTOR_SEARCH = False
        SEARCH_HNSW_EF_SEARCH = 100

    search_mod.Settings = _FakeSettings  # type: ignore[assignment]
    search_mod._vector_search = AsyncMock(return_value=[])
    search_mod._fts_search = AsyncMock(return_value=[person_row, project_row])
    search_mod._entity_name_search = AsyncMock(return_value=[])

    # Simulate the entity-type DB lookup: person_id → "person", project_id → "project"
    mock_session = AsyncMock()

    type_mapping_result = MagicMock()
    type_mapping_result.mappings.return_value = [
        {"id": person_id, "slug": "person"},
        {"id": project_id, "slug": "project"},
    ]
    mock_session.execute = AsyncMock(return_value=type_mapping_result)

    try:
        response = await search_mod.hybrid_search(
            session=mock_session,
            query="Alice",
            workspace_id=workspace_id,
            limit=10,
            entity_types=["person"],
        )
    finally:
        search_mod._vector_search = original_vector
        search_mod._fts_search = original_fts
        search_mod._entity_name_search = original_name
        search_mod.Settings = original_settings

    assert len(response.results) == 1, f"Expected 1 result (only person), got {len(response.results)}"
    assert response.results[0].source_id == person_id


@pytest.mark.asyncio
async def test_entity_types_none_returns_all_results():
    """When entity_types is None, no filtering occurs and all results are returned."""
    from alayaos_core.services import search as search_mod

    entity_id_a = uuid.uuid4()
    entity_id_b = uuid.uuid4()
    workspace_id = uuid.uuid4()

    rows = [
        {
            "source_type": "entity",
            "source_id": entity_id_a,
            "content": "Alice",
            "entity_id": entity_id_a,
            "entity_name": "Alice",
            "claim_id": None,
        },
        {
            "source_type": "entity",
            "source_id": entity_id_b,
            "content": "Orion",
            "entity_id": entity_id_b,
            "entity_name": "Orion",
            "claim_id": None,
        },
    ]

    original_vector = search_mod._vector_search
    original_fts = search_mod._fts_search
    original_name = search_mod._entity_name_search
    original_settings = search_mod.Settings

    class _FakeSettings:
        SEARCH_RRF_K = 60
        FEATURE_FLAG_VECTOR_SEARCH = False
        SEARCH_HNSW_EF_SEARCH = 100

    search_mod.Settings = _FakeSettings  # type: ignore[assignment]
    search_mod._vector_search = AsyncMock(return_value=[])
    search_mod._fts_search = AsyncMock(return_value=rows)
    search_mod._entity_name_search = AsyncMock(return_value=[])

    mock_session = AsyncMock()

    try:
        response = await search_mod.hybrid_search(
            session=mock_session,
            query="query",
            workspace_id=workspace_id,
            limit=10,
            entity_types=None,
        )
    finally:
        search_mod._vector_search = original_vector
        search_mod._fts_search = original_fts
        search_mod._entity_name_search = original_name
        search_mod.Settings = original_settings

    assert len(response.results) == 2, f"Expected 2 results when entity_types=None, got {len(response.results)}"
