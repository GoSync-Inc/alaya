"""L2 Claim endpoints."""

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
from alayaos_core.repositories.claim import ClaimRepository
from alayaos_core.schemas.claim import ClaimRead, ClaimUpdate

router = APIRouter()

# Valid status transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "active": {"retracted"},
    "retracted": {"active"},
}


def _not_found(claim_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Claim '{claim_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/claims")
async def list_claims(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
    entity_id: uuid.UUID | None = None,
    predicate: str | None = None,
    status: str | None = None,
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

    repo = ClaimRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(
        cursor=cursor,
        limit=limit,
        entity_id=entity_id,
        predicate=predicate,
        status=status,
    )
    filtered_count = getattr(repo, "last_filtered_count", 0)
    if not isinstance(filtered_count, int):
        filtered_count = 0
    return paginated_response(
        items,
        ClaimRead,
        next_cursor,
        has_more,
        filtered_count=filtered_count,
        filter_reason="acl_filtered",
    )


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = ClaimRepository(session, api_key.workspace_id)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise _not_found(str(claim_id))
    return data_response(ClaimRead.model_validate(claim))


@router.patch("/claims/{claim_id}")
async def update_claim(
    claim_id: uuid.UUID,
    body: ClaimUpdate,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    repo = ClaimRepository(session, api_key.workspace_id)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise _not_found(str(claim_id))

    if body.status is not None:
        allowed = _VALID_TRANSITIONS.get(claim.status, set())
        if body.status not in allowed:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "validation.invalid_transition",
                        "message": (
                            f"Cannot transition claim from '{claim.status}' to '{body.status}'. "
                            f"Valid transitions: {sorted(allowed) if allowed else 'none'}."
                        ),
                        "hint": "Valid transitions from 'active': retracted, disputed.",
                        "docs": None,
                        "request_id": None,
                    }
                },
            )
        claim = await repo.update_status(claim_id, body.status)

    return data_response(ClaimRead.model_validate(claim))
