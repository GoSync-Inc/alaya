"""Entity type endpoints."""

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
from alayaos_core.repositories.entity_type import EntityTypeRepository
from alayaos_core.schemas.entity_type import EntityTypeCreate, EntityTypeRead

router = APIRouter()


def _not_found(type_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Entity type '{type_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/entity-types")
async def list_entity_types(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
):
    repo = EntityTypeRepository(session)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    return paginated_response(items, EntityTypeRead, next_cursor, has_more)


@router.post("/entity-types", status_code=201)
async def create_entity_type(
    body: EntityTypeCreate,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    repo = EntityTypeRepository(session)
    try:
        entity_type = await repo.create(
            workspace_id=api_key.workspace_id,
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
            icon=body.icon,
            color=body.color,
        )
    except IntegrityError as e:
        existing = await repo.get_by_slug(api_key.workspace_id, body.slug)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "resource.already_exists",
                        "message": f"Entity type with slug '{body.slug}' already exists.",
                        "hint": None,
                        "docs": None,
                        "request_id": None,
                    }
                },
            ) from e
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "resource.constraint_violation",
                    "message": "Constraint violation when creating entity type.",
                    "hint": str(e.orig),
                    "docs": None,
                    "request_id": None,
                }
            },
        ) from e
    return data_response(EntityTypeRead.model_validate(entity_type))


@router.get("/entity-types/{type_id}")
async def get_entity_type(
    type_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = EntityTypeRepository(session)
    entity_type = await repo.get_by_id(type_id)
    if entity_type is None:
        raise _not_found(str(type_id))
    return data_response(EntityTypeRead.model_validate(entity_type))
