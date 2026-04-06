"""API key management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.api_key import APIKeyRepository
from alayaos_core.schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyRead
from alayaos_core.services.api_key import create_api_key

router = APIRouter()


@router.post("/api-keys", status_code=201)
async def create_api_key_endpoint(
    body: APIKeyCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    """Create a new API key. Returns raw key once — store it safely."""
    new_key, raw_key = await create_api_key(
        session=session,
        workspace_id=api_key.workspace_id,
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    response_data = APIKeyCreateResponse.model_validate(new_key)
    response_data = APIKeyCreateResponse(
        **APIKeyRead.model_validate(new_key).model_dump(),
        raw_key=raw_key,
    )
    return data_response(response_data)


@router.get("/api-keys")
async def list_api_keys(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
):
    """List API keys. Never returns raw keys."""
    repo = APIKeyRepository(session)
    items, next_cursor, has_more = await repo.list(
        workspace_id=api_key.workspace_id,
        cursor=cursor,
        limit=limit,
    )
    return paginated_response(items, APIKeyRead, next_cursor, has_more)


@router.delete("/api-keys/{prefix}", status_code=204)
async def revoke_api_key(
    prefix: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    """Revoke an API key by its prefix."""
    repo = APIKeyRepository(session)
    revoked = await repo.revoke(prefix)
    if revoked is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "resource.not_found",
                    "message": f"API key with prefix '{prefix}' not found.",
                    "hint": None,
                    "docs": None,
                    "request_id": None,
                }
            },
        )
