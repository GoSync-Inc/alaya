"""Admin endpoints for maintenance operations."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_session, require_scope
from alayaos_core.models.api_key import APIKey
from alayaos_core.services.embedding import EmbeddingServiceInterface

log = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


class BackfillRequest(BaseModel):
    workspace_id: uuid.UUID | None = None
    batch_size: int = Field(default=64, ge=1, le=200)


class BackfillResponse(BaseModel):
    processed: int
    failed: int
    total: int


def get_embedding_service() -> EmbeddingServiceInterface:
    """Provide the embedding service (FastEmbed in production)."""
    from alayaos_core.config import Settings
    from alayaos_core.services.embedding import FastEmbedService

    settings = Settings()
    return FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)  # type: ignore[return-value]


@router.post("/backfill-embeddings", response_model=BackfillResponse)
async def backfill_embeddings(
    request: BackfillRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_service: Annotated[EmbeddingServiceInterface, Depends(get_embedding_service)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
) -> BackfillResponse:
    """Backfill missing embeddings in vector_chunks.

    When workspace_id is provided, SET LOCAL app.workspace_id is applied so RLS
    filters to that workspace. When omitted, this is a cross-workspace admin
    operation — the admin key bypasses RLS by design.
    """
    # Apply RLS workspace filter when workspace_id is provided.
    if request.workspace_id is not None:
        validated_wid = str(uuid.UUID(str(request.workspace_id)))
        await session.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))

    # Build query for chunks with no embedding
    if request.workspace_id is not None:
        result = await session.execute(
            text(
                "SELECT id, content FROM vector_chunks"
                " WHERE embedding IS NULL AND workspace_id = :workspace_id"
                " LIMIT :batch_size"
            ),
            {"workspace_id": request.workspace_id, "batch_size": request.batch_size},
        )
    else:
        result = await session.execute(
            text(
                "SELECT id, content FROM vector_chunks"
                " WHERE embedding IS NULL"
                " LIMIT :batch_size"
            ),
            {"batch_size": request.batch_size},
        )

    rows = result.all()
    total = len(rows)

    if total == 0:
        return BackfillResponse(processed=0, failed=0, total=0)

    texts = [row.content for row in rows]
    ids = [row.id for row in rows]

    try:
        embeddings = await embedding_service.embed_texts(texts)
    except Exception:
        log.exception("backfill.embed_failed", count=total)
        return BackfillResponse(processed=0, failed=total, total=total)

    processed = 0
    failed = 0
    for chunk_id, embedding in zip(ids, embeddings, strict=True):
        try:
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE vector_chunks SET embedding = :embedding WHERE id = :id"
                    ),
                    {"embedding": str(embedding), "id": chunk_id},
                )
            processed += 1
        except Exception:
            log.warning("backfill_chunk_failed", chunk_id=str(chunk_id))
            failed += 1

    return BackfillResponse(processed=processed, failed=failed, total=total)
