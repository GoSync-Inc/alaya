"""Admin endpoints for maintenance operations."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import _error_response, get_session, require_scope
from alayaos_core.config import FEATURE_FLAG_DEFAULTS, get_settings
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


async def _count_tier_violations_24h(_session: AsyncSession) -> None:
    return None


@router.get("/flags")
async def get_admin_flags(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
) -> dict:
    """Return process-level feature flag state for bootstrap administrators."""
    if not api_key.is_bootstrap:
        log.warning("admin_flags_denied", key_prefix=api_key.key_prefix, reason="bootstrap_required")
        raise HTTPException(
            status_code=403,
            detail=_error_response(
                "auth.bootstrap_required",
                "Bootstrap admin key is required for feature flag state.",
                hint="Use the bootstrap key for process-level feature flag inspection.",
            ),
        )

    settings = get_settings()
    violations_last_24h = await _count_tier_violations_24h(session)
    data = {}
    flags_non_default = 0
    for name, default in FEATURE_FLAG_DEFAULTS:
        value = getattr(settings, name)
        non_default = value != default
        if non_default:
            flags_non_default += 1
        data[name] = {
            "value": value,
            "default": default,
            "non_default": non_default,
            "violations_last_24h": violations_last_24h,
            "violations_last_24h_reason": "counter_not_yet_instrumented",
        }
    return {"data": data, "meta": {"flags_non_default": flags_non_default}}


@router.post("/backfill-embeddings", response_model=BackfillResponse)
async def backfill_embeddings(
    request: BackfillRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_service: Annotated[EmbeddingServiceInterface, Depends(get_embedding_service)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
) -> BackfillResponse:
    """Backfill missing embeddings in vector_chunks.

    Non-bootstrap admin keys must provide workspace_id and may only operate on
    their own workspace.  Bootstrap keys may specify any workspace_id or omit it
    to operate across all workspaces.
    """
    if not api_key.is_bootstrap:
        # Non-bootstrap: workspace_id is required.
        if request.workspace_id is None:
            log.warning("admin_cross_workspace_attempt", key_prefix=api_key.key_prefix, reason="missing_workspace_id")
            raise HTTPException(
                status_code=422,
                detail=_error_response(
                    "workspace_required_for_admin_scope",
                    "workspace_id is required for non-bootstrap admin keys.",
                    hint="Provide the workspace_id you own, or use a bootstrap key for cross-workspace operations.",
                ),
            )
        # Non-bootstrap: can only operate on their own workspace.
        if request.workspace_id != api_key.workspace_id:
            log.warning(
                "admin_cross_workspace_attempt",
                key_prefix=api_key.key_prefix,
                requested_workspace=str(request.workspace_id),
                key_workspace=str(api_key.workspace_id),
            )
            raise HTTPException(
                status_code=403,
                detail=_error_response(
                    "auth.cross_workspace_denied",
                    "Admin key may not operate on a different workspace.",
                    hint="Use a bootstrap key for cross-workspace operations.",
                ),
            )

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
            text("SELECT id, content FROM vector_chunks WHERE embedding IS NULL LIMIT :batch_size"),
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
                    text("UPDATE vector_chunks SET embedding = :embedding WHERE id = :id"),
                    {"embedding": str(embedding), "id": chunk_id},
                )
            processed += 1
        except Exception:
            log.warning("backfill_chunk_failed", chunk_id=str(chunk_id))
            failed += 1

    return BackfillResponse(processed=processed, failed=failed, total=total)
