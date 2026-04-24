"""Hybrid search service with 3-channel Reciprocal Rank Fusion."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text
from structlog.contextvars import get_contextvars

from alayaos_core.config import Settings
from alayaos_core.schemas.search import EvidenceUnit, SearchResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.services.embedding import EmbeddingServiceInterface

log = structlog.get_logger()

RRF_K = 60  # default, overridden by Settings


@dataclass(frozen=True, slots=True)
class ChannelSearchResult:
    rows: list[dict]
    filtered_count: int = 0


class SearchServiceResponse(SearchResponse):
    meta: dict[str, object]


def _channel_rows(result: ChannelSearchResult | list[dict]) -> list[dict]:
    return result.rows if isinstance(result, ChannelSearchResult) else result


def _channel_filtered_count(result: ChannelSearchResult | list[dict]) -> int:
    return result.filtered_count if isinstance(result, ChannelSearchResult) else 0


async def hybrid_search(
    session: AsyncSession,
    query: str,
    workspace_id: uuid.UUID,
    *,
    embedding_service: EmbeddingServiceInterface | None = None,
    limit: int = 10,
    entity_types: list[str] | None = None,
) -> SearchResponse:
    """3-channel RRF search: vector + FTS + entity name."""
    settings = Settings()
    k = settings.SEARCH_RRF_K
    vector_enabled = settings.FEATURE_FLAG_VECTOR_SEARCH and embedding_service is not None

    start = time.monotonic()
    channels_used: list[str] = []
    all_results: dict[str, dict] = {}  # key = f"{source_type}:{source_id}"
    channel_breakdown: dict[str, int] = {}

    # Channel 1: Vector search (conditional)
    if vector_enabled:
        query_embedding = await embedding_service.embed_text(query)
        vector_results = await _vector_search(session, query_embedding, workspace_id, limit * 2)
        channel_breakdown["vector"] = _channel_filtered_count(vector_results)
        channels_used.append("vector")
        for rank, row in enumerate(_channel_rows(vector_results), 1):
            key = f"{row['source_type']}:{row['source_id']}"
            entry = all_results.setdefault(key, {**row, "rrf_score": 0.0, "channels": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            entry["channels"].append("vector")

    # Channel 2: FTS search
    fts_results = await _fts_search(session, query, workspace_id, limit * 2)
    channel_breakdown["fts"] = _channel_filtered_count(fts_results)
    fts_rows = _channel_rows(fts_results)
    if fts_rows:
        channels_used.append("fts")
        for rank, row in enumerate(fts_rows, 1):
            key = f"{row['source_type']}:{row['source_id']}"
            entry = all_results.setdefault(key, {**row, "rrf_score": 0.0, "channels": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            if "fts" not in entry["channels"]:
                entry["channels"].append("fts")

    # Channel 3: Entity name search (pg_trgm)
    name_results = await _entity_name_search(session, query, workspace_id, limit * 2)
    channel_breakdown["entity_name"] = _channel_filtered_count(name_results)
    name_rows = _channel_rows(name_results)
    if name_rows:
        channels_used.append("entity_name")
        for rank, row in enumerate(name_rows, 1):
            key = f"{row['source_type']}:{row['source_id']}"
            entry = all_results.setdefault(key, {**row, "rrf_score": 0.0, "channels": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            if "entity_name" not in entry["channels"]:
                entry["channels"].append("entity_name")

    # Sort by RRF score
    sorted_results = sorted(all_results.values(), key=lambda x: x["rrf_score"], reverse=True)

    # Filter by entity_types if provided (post-RRF to preserve correct scoring)
    if entity_types:
        entity_ids = [r["source_id"] for r in sorted_results if r["source_type"] == "entity"]
        if entity_ids:
            type_sql = text("""
                SELECT e.id, et.slug FROM l1_entities e
                JOIN entity_type_definitions et ON et.id = e.entity_type_id AND et.workspace_id = e.workspace_id
                WHERE e.id = ANY(:ids) AND e.workspace_id = :ws_id
            """)
            type_result = await session.execute(type_sql, {"ids": entity_ids, "ws_id": workspace_id})
            entity_type_map = {row["id"]: row["slug"] for row in type_result.mappings()}
            sorted_results = [
                r
                for r in sorted_results
                if r["source_type"] != "entity" or entity_type_map.get(r["source_id"]) in entity_types
            ]

    # Apply limit
    sorted_results = sorted_results[:limit]

    elapsed_ms = int((time.monotonic() - start) * 1000)
    positive_breakdown = {channel: count for channel, count in channel_breakdown.items() if count > 0}
    total_filtered = sum(positive_breakdown.values())

    if total_filtered > 0:
        context = get_contextvars()
        log_payload: dict[str, object] = {
            "channel_breakdown": positive_breakdown,
            "total_filtered": total_filtered,
        }
        if allowed := context.get("allowed_access_levels"):
            log_payload["allowed_access_levels"] = allowed
        if scope := context.get("scope"):
            log_payload["scope"] = scope
        log.info("retrieval.acl_filtered", **log_payload)

    results = [
        EvidenceUnit(
            source_type=r["source_type"],
            source_id=r["source_id"],
            content=r["content"],
            score=round(r["rrf_score"], 6),
            channels=r["channels"],
            entity_id=r.get("entity_id"),
            entity_name=r.get("entity_name"),
            claim_id=r.get("claim_id"),
            confidence=r.get("confidence"),
        )
        for r in sorted_results
    ]

    return SearchServiceResponse(
        query=query,
        results=results,
        total=len(results),
        channels_used=channels_used,
        elapsed_ms=elapsed_ms,
        meta={
            "filtered_count": total_filtered,
            "filter_reason": "acl_filtered" if total_filtered > 0 else None,
        },
    )


async def _vector_search(
    session: AsyncSession, query_embedding: list[float], workspace_id: uuid.UUID, limit: int
) -> ChannelSearchResult:
    """Vector similarity search using pgvector HNSW cosine."""
    settings = Settings()
    ef = int(settings.SEARCH_HNSW_EF_SEARCH)
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef}"))
    count_sql = text("""
        WITH candidates AS (
            SELECT vc.id
            FROM vector_chunks vc
            WHERE vc.workspace_id = :ws_id
              AND vc.source_type <> 'entity'
            ORDER BY vc.embedding <=> :embedding::halfvec
            LIMIT :lim
        )
        SELECT COUNT(*) FROM candidates
    """)
    count_result = await session.execute(
        count_sql, {"embedding": str(query_embedding), "ws_id": workspace_id, "lim": limit}
    )
    pre_count = int(count_result.scalar_one())
    sql = text("""
        SELECT
            vc.source_id AS source_id,
            vc.source_type,
            vc.content,
            vc.id AS chunk_id,
            1 - (vc.embedding <=> :embedding::halfvec) AS similarity
        FROM vector_chunks vc
        WHERE vc.workspace_id = :ws_id
          AND vc.source_type <> 'entity'
          AND vc.access_level = ANY(alaya_current_allowed_access())
        ORDER BY vc.embedding <=> :embedding::halfvec
        LIMIT :lim
    """)
    result = await session.execute(sql, {"embedding": str(query_embedding), "ws_id": workspace_id, "lim": limit})
    rows = []
    for row in result.mappings():
        rows.append(
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "content": row["content"],
                "entity_id": row["source_id"] if row["source_type"] == "entity" else None,
                "entity_name": None,
                "claim_id": row["source_id"] if row["source_type"] == "claim" else None,
            }
        )
    return ChannelSearchResult(rows=rows, filtered_count=max(pre_count - len(rows), 0))


async def _fts_search(session: AsyncSession, query: str, workspace_id: uuid.UUID, limit: int) -> ChannelSearchResult:
    """Full-text search on vector_chunks and l1_entities tsvector columns."""
    count_sql = text("""
        SELECT
            (
                SELECT COUNT(*)
                FROM vector_chunks vc
                WHERE vc.workspace_id = :ws_id
                  AND vc.source_type <> 'entity'
                  AND vc.tsv @@ websearch_to_tsquery('simple', :query)
            )
            +
            (
                SELECT COUNT(*)
                FROM l1_entities e
                JOIN l2_claims c
                  ON c.entity_id = e.id
                 AND c.workspace_id = e.workspace_id
                 AND c.status = 'active'
                JOIN claim_effective_access cea
                  ON cea.claim_id = c.id AND cea.workspace_id = c.workspace_id
                WHERE e.workspace_id = :ws_id
                  AND e.is_deleted = false
                  AND cea.max_tier_rank <= (
                      SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x
                  )
                  AND to_tsvector('simple', e.name || ' ' || c.predicate || ' ' || c.value::text)
                      @@ websearch_to_tsquery('simple', :query)
            ) AS pre_count
    """)
    count_result = await session.execute(count_sql, {"query": query, "ws_id": workspace_id})
    pre_count = int(count_result.scalar_one())
    sql = text("""
        WITH chunk_fts AS (
            SELECT vc.source_id AS source_id, vc.source_type AS source_type, vc.content,
                   vc.source_id AS ref_id, vc.source_type AS ref_type,
                   ts_rank(vc.tsv, websearch_to_tsquery('simple', :query)) AS rank
            FROM vector_chunks vc
            WHERE vc.workspace_id = :ws_id
              AND vc.source_type <> 'entity'
              AND vc.tsv @@ websearch_to_tsquery('simple', :query)
              AND vc.access_level = ANY(alaya_current_allowed_access())
            ORDER BY rank DESC
            LIMIT :lim
        ),
        entity_fts AS (
            SELECT e.id AS source_id, 'entity' AS source_type,
                   e.name || ': ' || string_agg(c.predicate || ': ' || c.value::text, '; ' ORDER BY c.created_at DESC) AS content,
                   e.id AS ref_id, 'entity' AS ref_type,
                   MAX(
                       ts_rank(
                           to_tsvector('simple', e.name || ' ' || c.predicate || ' ' || c.value::text),
                           websearch_to_tsquery('simple', :query)
                       )
                   ) AS rank
            FROM l1_entities e
            JOIN l2_claims c
              ON c.entity_id = e.id
             AND c.workspace_id = e.workspace_id
             AND c.status = 'active'
            JOIN claim_effective_access cea
              ON cea.claim_id = c.id AND cea.workspace_id = c.workspace_id
            WHERE e.workspace_id = :ws_id
              AND e.is_deleted = false
              AND cea.max_tier_rank <= (
                  SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x
              )
              AND to_tsvector('simple', e.name || ' ' || c.predicate || ' ' || c.value::text)
                  @@ websearch_to_tsquery('simple', :query)
            GROUP BY e.id, e.name
            ORDER BY rank DESC
            LIMIT :lim
        )
        SELECT * FROM chunk_fts
        UNION ALL
        SELECT * FROM entity_fts
        ORDER BY rank DESC
        LIMIT :lim
    """)
    result = await session.execute(sql, {"query": query, "ws_id": workspace_id, "lim": limit})
    rows = []
    for row in result.mappings():
        rows.append(
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "content": row["content"],
                "entity_id": row["ref_id"] if row["ref_type"] == "entity" else None,
                "entity_name": None,
                "claim_id": row["ref_id"] if row["ref_type"] == "claim" else None,
            }
        )
    return ChannelSearchResult(rows=rows, filtered_count=max(pre_count - len(rows), 0))


async def _entity_name_search(
    session: AsyncSession, query: str, workspace_id: uuid.UUID, limit: int
) -> ChannelSearchResult:
    """Entity name fuzzy search using pg_trgm similarity."""
    count_sql = text("""
        WITH candidates AS (
            SELECT e.id AS source_id
            FROM l1_entities e
            WHERE e.workspace_id = :ws_id
              AND e.is_deleted = false
              AND similarity(e.name, :query) > 0.1
            ORDER BY similarity(e.name, :query) DESC
            LIMIT (:lim * 3)
        )
        SELECT COUNT(*) FROM candidates
    """)
    count_result = await session.execute(count_sql, {"query": query, "ws_id": workspace_id, "lim": limit})
    candidate_count = int(count_result.scalar_one())
    sql = text("""
        WITH candidates AS (
            SELECT e.id AS source_id, e.name,
                   similarity(e.name, :query) AS sim
            FROM l1_entities e
            WHERE e.workspace_id = :ws_id
              AND e.is_deleted = false
              AND similarity(e.name, :query) > 0.1
            ORDER BY sim DESC
            LIMIT (:lim * 3)
        ),
        visible_claims AS (
            SELECT cl.entity_id,
                   string_agg(cl.predicate || ': ' || cl.value::text, '; ' ORDER BY cl.created_at DESC) AS claims_text
            FROM l2_claims cl
            JOIN claim_effective_access cea
              ON cea.claim_id = cl.id AND cea.workspace_id = cl.workspace_id
            WHERE cl.workspace_id = :ws_id
              AND cl.status = 'active'
              AND cea.max_tier_rank <= (
                  SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x
              )
            GROUP BY cl.entity_id
        )
        SELECT c.source_id, 'entity' AS source_type,
               c.name || ': ' || vc.claims_text AS content,
               c.name AS entity_name, c.sim
        FROM candidates c
        JOIN visible_claims vc ON vc.entity_id = c.source_id
        ORDER BY c.sim DESC
        LIMIT :lim
    """)
    result = await session.execute(sql, {"query": query, "ws_id": workspace_id, "lim": limit})
    rows = []
    for row in result.mappings():
        rows.append(
            {
                "source_type": "entity",
                "source_id": row["source_id"],
                "content": row["content"],
                "entity_id": row["source_id"],
                "entity_name": row["entity_name"],
            }
        )
    return ChannelSearchResult(rows=rows, filtered_count=max(candidate_count - len(rows), 0))
