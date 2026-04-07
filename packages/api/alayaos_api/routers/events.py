"""L0 Event endpoints."""

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
from alayaos_core.repositories.event import EventRepository
from alayaos_core.schemas.event import EventCreate, EventRead

router = APIRouter()


def _not_found(event_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Event '{event_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.post("/events", status_code=201)
async def create_event(
    body: EventCreate,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    repo = EventRepository(session, api_key.workspace_id)
    event, _created = await repo.create_or_update(
        workspace_id=api_key.workspace_id,
        source_type=body.source_type,
        source_id=body.source_id,
        content=body.content,
        metadata=body.metadata,
    )
    return data_response(EventRead.model_validate(event))


@router.get("/events")
async def list_events(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
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

    repo = EventRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    return paginated_response(items, EventRead, next_cursor, has_more)


@router.get("/events/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = EventRepository(session, api_key.workspace_id)
    event = await repo.get_by_id(event_id)
    if event is None:
        raise _not_found(str(event_id))
    return data_response(EventRead.model_validate(event))
