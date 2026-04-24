"""ACL-filtered HNSW recall checks against exact pgvector scans."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


DIMENSIONS = 1024


def _embedding(primary_value: float, secondary_value: float = 0.0) -> str:
    values = [0.0] * DIMENSIONS
    values[0] = primary_value
    values[1] = secondary_value
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


async def _insert_vector_chunk(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    source_id: uuid.UUID,
    chunk_index: int,
    content: str,
    access_level: str,
    embedding: str,
) -> None:
    await session.execute(
        text("""
            INSERT INTO vector_chunks (
                id, workspace_id, source_type, source_id, chunk_index, content, access_level, embedding
            )
            VALUES (
                :id, :workspace_id, 'event', :source_id, :chunk_index, :content, :access_level,
                CAST(:embedding AS halfvec)
            )
        """),
        {
            "id": uuid.uuid4(),
            "workspace_id": workspace_id,
            "source_id": source_id,
            "chunk_index": chunk_index,
            "content": content,
            "access_level": access_level,
            "embedding": embedding,
        },
    )


async def _vector_result_ids(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query_embedding: str,
    use_index: bool,
    limit: int,
) -> list[uuid.UUID]:
    if use_index:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        await session.execute(text("SET LOCAL enable_indexscan = on"))
        await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    else:
        await session.execute(text("SET LOCAL enable_seqscan = on"))
        await session.execute(text("SET LOCAL enable_indexscan = off"))

    result = await session.execute(
        text("""
            SELECT source_id
            FROM vector_chunks
            WHERE workspace_id = :workspace_id
              AND source_type = 'event'
              AND access_level = ANY(alaya_current_allowed_access())
            ORDER BY embedding <=> CAST(:embedding AS halfvec)
            LIMIT :limit
        """),
        {"workspace_id": workspace_id, "embedding": query_embedding, "limit": limit},
    )
    return [row.source_id for row in result.all()]


async def test_acl_filtered_hnsw_recall_matches_exact_scan(db_session: AsyncSession, workspace) -> None:
    """HNSW candidates visible under ACL filtering should match exact-scan top-K."""
    public_source_ids = [uuid.uuid4() for _ in range(8)]
    for index, source_id in enumerate(public_source_ids):
        await _insert_vector_chunk(
            db_session,
            workspace.id,
            source_id=source_id,
            chunk_index=index,
            content=f"public recall candidate {index}",
            access_level="public",
            embedding=_embedding(1.0 - (index * 0.01), index * 0.001),
        )

    for index in range(8):
        await _insert_vector_chunk(
            db_session,
            workspace.id,
            source_id=uuid.uuid4(),
            chunk_index=100 + index,
            content=f"restricted near-neighbor {index}",
            access_level="restricted",
            embedding=_embedding(1.0 - (index * 0.005), 0.5),
        )

    await db_session.flush()
    await db_session.execute(text("SELECT set_config('app.allowed_access_levels', 'public,channel', true)"))
    query_embedding = _embedding(1.0, 0.0)

    exact_ids = await _vector_result_ids(
        db_session,
        workspace.id,
        query_embedding=query_embedding,
        use_index=False,
        limit=5,
    )
    hnsw_ids = await _vector_result_ids(
        db_session,
        workspace.id,
        query_embedding=query_embedding,
        use_index=True,
        limit=5,
    )

    assert exact_ids == public_source_ids[:5]
    assert hnsw_ids == exact_ids
