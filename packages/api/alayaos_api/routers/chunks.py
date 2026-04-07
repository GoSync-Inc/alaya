"""L0Chunk endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.chunk import ChunkRepository
from alayaos_core.schemas.chunk import ChunkRead

router = APIRouter()


def _not_found(chunk_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Chunk '{chunk_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/chunks")
async def list_chunks(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
    processing_stage: Annotated[str | None, Query()] = None,
    is_crystal: Annotated[bool | None, Query()] = None,
):
    if cursor is not None:
        try:
            BaseRepository.decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "validation.invalid_cursor",
                        "message": "Invalid pagination cursor.",
                        "hint": None,
                        "docs": None,
                        "request_id": None,
                    }
                },
            ) from e

    repo = ChunkRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(
        cursor=cursor,
        limit=limit,
        processing_stage=processing_stage,
        is_crystal=is_crystal,
    )
    return paginated_response(items, ChunkRead, next_cursor, has_more)


@router.get("/chunks/{chunk_id}")
async def get_chunk(
    chunk_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = ChunkRepository(session, api_key.workspace_id)
    chunk = await repo.get_by_id(chunk_id)
    if chunk is None:
        raise _not_found(str(chunk_id))
    return data_response(ChunkRead.model_validate(chunk))
