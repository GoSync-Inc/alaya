"""L1 Relation endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.relation import RelationRepository
from alayaos_core.schemas.relation import RelationRead

router = APIRouter()


def _not_found(relation_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Relation '{relation_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/relations")
async def list_relations(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
    entity_id: uuid.UUID | None = None,
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

    repo = RelationRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit, entity_id=entity_id)
    return paginated_response(items, RelationRead, next_cursor, has_more)


@router.get("/relations/{relation_id}")
async def get_relation(
    relation_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = RelationRepository(session, api_key.workspace_id)
    relation = await repo.get_by_id(relation_id)
    if relation is None:
        raise _not_found(str(relation_id))
    return data_response(RelationRead.model_validate(relation))
