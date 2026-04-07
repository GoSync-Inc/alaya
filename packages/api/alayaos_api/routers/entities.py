"""Entity CRUD endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.schemas.entity import EntityCreate, EntityRead, EntityUpdate

router = APIRouter()


def _not_found(entity_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Entity '{entity_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.post("/entities", status_code=201)
async def create_entity(
    body: EntityCreate,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    repo = EntityRepository(session, api_key.workspace_id)
    try:
        entity = await repo.create(
            workspace_id=api_key.workspace_id,
            entity_type_id=body.entity_type_id,
            name=body.name,
            description=body.description,
            properties=body.properties,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "resource.constraint_violation",
                    "message": "Constraint violation when creating entity.",
                    "hint": str(e.orig),
                    "docs": None,
                    "request_id": None,
                }
            },
        ) from e
    return data_response(EntityRead.model_validate(entity))


@router.get("/entities")
async def list_entities(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
    type_slug: str | None = None,
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

    repo = EntityRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit, type_slug=type_slug)
    return paginated_response(items, EntityRead, next_cursor, has_more)


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = EntityRepository(session, api_key.workspace_id)
    entity = await repo.get_by_id(entity_id)
    if entity is None:
        raise _not_found(str(entity_id))
    return data_response(EntityRead.model_validate(entity))


@router.patch("/entities/{entity_id}")
async def update_entity(
    entity_id: uuid.UUID,
    body: EntityUpdate,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    repo = EntityRepository(session, api_key.workspace_id)
    updates = body.model_dump(exclude_none=True)
    entity = await repo.update(entity_id, **updates)
    if entity is None:
        raise _not_found(str(entity_id))
    return data_response(EntityRead.model_validate(entity))


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    repo = EntityRepository(session, api_key.workspace_id)
    entity = await repo.update(entity_id, is_deleted=True)
    if entity is None:
        raise _not_found(str(entity_id))
