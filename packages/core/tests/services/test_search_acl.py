"""ACL-focused tests for retrieval services."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.testing import capture_logs


@pytest.mark.asyncio
async def test_vector_search_filters_by_allowed_access_and_reports_filtered_count():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    source_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    captured_sql: list[str] = []

    async def execute(statement, params=None):
        sql = str(statement)
        captured_sql.append(sql)
        if "COUNT(*)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = 2
            return result
        if "FROM vector_chunks vc" in sql:
            result = MagicMock()
            result.mappings.return_value = [
                {
                    "source_type": "claim",
                    "source_id": source_id,
                    "content": "restricted-safe row",
                    "chunk_id": chunk_id,
                    "similarity": 0.9,
                }
            ]
            return result
        return MagicMock()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)

    result = await search_mod._vector_search(session, [0.1, 0.2], workspace_id, 10)

    vector_sql = "\n".join(captured_sql)
    assert "vc.access_level = ANY(alaya_current_allowed_access())" in vector_sql
    assert "vc.source_type <> 'entity'" in vector_sql
    assert "COUNT(*)" in vector_sql
    assert getattr(result, "filtered_count", None) == 1
    assert result.rows[0]["source_id"] == source_id


@pytest.mark.asyncio
async def test_fts_search_filters_chunks_and_entities_by_allowed_access():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    captured_sql: list[str] = []

    async def execute(statement, params=None):
        sql = str(statement)
        captured_sql.append(sql)
        if "COUNT(*)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = 2
            return result
        result = MagicMock()
        result.mappings.return_value = [
            {
                "source_type": "entity",
                "source_id": entity_id,
                "content": "Acme: visible public claim",
                "ref_id": entity_id,
                "ref_type": "entity",
                "rank": 0.8,
            }
        ]
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)

    result = await search_mod._fts_search(session, "Acme", workspace_id, 10)

    fts_sql = "\n".join(captured_sql)
    assert "vc.access_level = ANY(alaya_current_allowed_access())" in fts_sql
    assert "vc.source_type <> 'entity'" in fts_sql
    assert "JOIN claim_effective_access cea" in fts_sql
    assert "cea.max_tier_rank <=" in fts_sql
    assert "MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x" in fts_sql
    assert getattr(result, "filtered_count", None) == 1
    assert result.rows[0]["entity_id"] == entity_id


@pytest.mark.asyncio
async def test_fts_entity_evidence_does_not_match_or_return_entity_descriptions():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    captured_sql: list[str] = []

    async def execute(statement, params=None):
        sql = str(statement)
        captured_sql.append(sql)
        if "COUNT(*)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = 0
            return result
        result = MagicMock()
        result.mappings.return_value = []
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)

    await search_mod._fts_search(session, "restricted-description-token", workspace_id, 10)

    query_sql = captured_sql[-1]
    assert "e.tsv @@" not in query_sql
    assert "e.description" not in query_sql
    assert "to_tsvector('simple', e.name || ' ' || c.predicate || ' ' || c.value::text)" in query_sql


@pytest.mark.asyncio
async def test_entity_name_search_overfetches_candidates_before_acl_filtering():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    captured_sql: list[str] = []

    async def execute(statement, params=None):
        sql = str(statement)
        captured_sql.append(sql)
        if "COUNT(*)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = 3
            return result
        result = MagicMock()
        result.mappings.return_value = [
            {
                "source_type": "entity",
                "source_id": entity_id,
                "content": "Acme: visible claim",
                "entity_name": "Acme",
                "sim": 0.7,
            }
        ]
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)

    result = await search_mod._entity_name_search(session, "Acme", workspace_id, 10)

    name_sql = "\n".join(captured_sql)
    assert "WITH candidates AS" in name_sql
    assert "LIMIT (:lim * 3)" in name_sql
    assert "JOIN claim_effective_access cea" in name_sql
    assert "cea.max_tier_rank <=" in name_sql
    assert "MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x" in name_sql
    assert getattr(result, "filtered_count", None) == 2
    assert result.rows[0]["entity_name"] == "Acme"


@pytest.mark.asyncio
async def test_entity_name_evidence_does_not_return_entity_description():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    captured_sql: list[str] = []

    async def execute(statement, params=None):
        sql = str(statement)
        captured_sql.append(sql)
        if "COUNT(*)" in sql:
            result = MagicMock()
            result.scalar_one.return_value = 0
            return result
        result = MagicMock()
        result.mappings.return_value = []
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)

    await search_mod._entity_name_search(session, "Acme", workspace_id, 10)

    query_sql = captured_sql[-1]
    assert "l.description" not in query_sql
    assert "visible_claims" in query_sql
    assert "string_agg(cl.predicate || ': ' || cl.value::text" in query_sql


@pytest.mark.asyncio
async def test_hybrid_search_aggregates_filtered_counts_and_logs_acl_event():
    from alayaos_core.services import search as search_mod

    workspace_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    visible_row = {
        "source_type": "entity",
        "source_id": entity_id,
        "content": "Acme: visible claim",
        "entity_id": entity_id,
        "entity_name": "Acme",
        "claim_id": None,
    }

    original_settings = search_mod.Settings
    original_fts = search_mod._fts_search
    original_name = search_mod._entity_name_search

    class _FakeSettings:
        SEARCH_RRF_K = 60
        FEATURE_FLAG_VECTOR_SEARCH = False
        SEARCH_HNSW_EF_SEARCH = 100

    search_mod.Settings = _FakeSettings  # type: ignore[assignment]
    search_mod._fts_search = AsyncMock(
        return_value=search_mod.ChannelSearchResult(rows=[visible_row], filtered_count=2)
    )
    search_mod._entity_name_search = AsyncMock(return_value=search_mod.ChannelSearchResult(rows=[], filtered_count=1))

    clear_contextvars()
    bind_contextvars(allowed_access_levels="channel,public")
    try:
        with capture_logs() as logs:
            response = await search_mod.hybrid_search(
                session=MagicMock(),
                query="Acme",
                workspace_id=workspace_id,
                limit=10,
            )
    finally:
        clear_contextvars()
        search_mod.Settings = original_settings
        search_mod._fts_search = original_fts
        search_mod._entity_name_search = original_name

    assert response.meta["filtered_count"] == 3
    assert response.meta["filter_reason"] == "acl_filtered"
    event = next(log for log in logs if log["event"] == "retrieval.acl_filtered")
    assert event["total_filtered"] == 3
    assert event["channel_breakdown"] == {"fts": 2, "entity_name": 1}
    assert event["allowed_access_levels"] == "channel,public"
