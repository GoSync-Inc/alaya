"""Predicate definition endpoints."""

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
from alayaos_core.repositories.predicate import PredicateRepository
from alayaos_core.schemas.predicate import PredicateRead

router = APIRouter()


def _not_found(predicate_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Predicate '{predicate_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/predicates")
async def list_predicates(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
):
    repo = PredicateRepository(session)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    return paginated_response(items, PredicateRead, next_cursor, has_more)


@router.get("/predicates/{predicate_id}")
async def get_predicate(
    predicate_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = PredicateRepository(session)
    predicate = await repo.get_by_id(predicate_id)
    if predicate is None:
        raise _not_found(str(predicate_id))
    return data_response(PredicateRead.model_validate(predicate))
