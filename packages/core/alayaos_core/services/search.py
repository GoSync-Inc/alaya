"""Hybrid search service with 3-channel Reciprocal Rank Fusion."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

from alayaos_core.config import Settings
from alayaos_core.schemas.search import EvidenceUnit, SearchResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.services.embedding import EmbeddingServiceInterface

log = structlog.get_logger()

RRF_K = 60  # default, overridden by Settings


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

    # Channel 1: Vector search (conditional)
    if vector_enabled:
        query_embedding = await embedding_service.embed_text(query)
        vector_results = await _vector_search(session, query_embedding, workspace_id, limit * 2)
        channels_used.append("vector")
        for rank, row in enumerate(vector_results, 1):
            key = f"{row['source_type']}:{row['source_id']}"
            entry = all_results.setdefault(key, {**row, "rrf_score": 0.0, "channels": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            entry["channels"].append("vector")

    # Channel 2: FTS search
    fts_results = await _fts_search(session, query, workspace_id, limit * 2)
    if fts_results:
        channels_used.append("fts")
        for rank, row in enumerate(fts_results, 1):
            key = f"{row['source_type']}:{row['source_id']}"
            entry = all_results.setdefault(key, {**row, "rrf_score": 0.0, "channels": []})
            entry["rrf_score"] += 1.0 / (k + rank)
            if "fts" not in entry["channels"]:
                entry["channels"].append("fts")

    # Channel 3: Entity name search (pg_trgm)
    name_results = await _entity_name_search(session, query, workspace_id, limit * 2)
    if name_results:
        channels_used.append("entity_name")
        for rank, row in enumerate(name_results, 1):
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

    return SearchResponse(
        query=query,
        results=results,
        total=len(results),
        channels_used=channels_used,
        elapsed_ms=elapsed_ms,
    )


async def _vector_search(
    session: AsyncSession, query_embedding: list[float], workspace_id: uuid.UUID, limit: int
) -> list[dict]:
    """Vector similarity search using pgvector HNSW cosine."""
    settings = Settings()
    ef = int(settings.SEARCH_HNSW_EF_SEARCH)
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef}"))
    sql = text("""
        SELECT
            vc.source_id AS source_id,
            vc.source_type,
            vc.content,
            vc.id AS chunk_id,
            1 - (vc.embedding <=> :embedding::halfvec) AS similarity
        FROM vector_chunks vc
        WHERE vc.workspace_id = :ws_id
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
    return rows


async def _fts_search(session: AsyncSession, query: str, workspace_id: uuid.UUID, limit: int) -> list[dict]:
    """Full-text search on vector_chunks and l1_entities tsvector columns."""
    sql = text("""
        WITH chunk_fts AS (
            SELECT vc.source_id AS source_id, vc.source_type AS source_type, vc.content,
                   vc.source_id AS ref_id, vc.source_type AS ref_type,
                   ts_rank(vc.tsv, websearch_to_tsquery('simple', :query)) AS rank
            FROM vector_chunks vc
            WHERE vc.workspace_id = :ws_id
              AND vc.tsv @@ websearch_to_tsquery('simple', :query)
            ORDER BY rank DESC
            LIMIT :lim
        ),
        entity_fts AS (
            SELECT e.id AS source_id, 'entity' AS source_type,
                   e.name || ': ' || COALESCE(e.description, '') AS content,
                   e.id AS ref_id, 'entity' AS ref_type,
                   ts_rank(e.tsv, websearch_to_tsquery('simple', :query)) AS rank
            FROM l1_entities e
            WHERE e.workspace_id = :ws_id
              AND e.is_deleted = false
              AND e.tsv @@ websearch_to_tsquery('simple', :query)
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
    return rows


async def _entity_name_search(session: AsyncSession, query: str, workspace_id: uuid.UUID, limit: int) -> list[dict]:
    """Entity name fuzzy search using pg_trgm similarity."""
    sql = text("""
        SELECT e.id AS source_id, 'entity' AS source_type,
               e.name || ': ' || COALESCE(e.description, '') AS content,
               e.name AS entity_name,
               similarity(e.name, :query) AS sim
        FROM l1_entities e
        WHERE e.workspace_id = :ws_id
          AND e.is_deleted = false
          AND similarity(e.name, :query) > 0.1
        ORDER BY sim DESC
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
    return rows
