"""Search endpoint."""

import contextlib
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_api_key, get_workspace_session
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.schemas.search import SearchRequest, SearchResponse
from alayaos_core.services.rate_limiter import RateLimiterService
from alayaos_core.services.search import hybrid_search

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
):
    settings = Settings()

    # Rate limiting
    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL)
    limiter = RateLimiterService(redis=redis_client)
    allowed, retry_after = await limiter.check(f"{api_key.prefix}:search", 60, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(retry_after)})

    embedding_service = None
    if settings.FEATURE_FLAG_VECTOR_SEARCH:
        from alayaos_core.services.embedding import FastEmbedService

        embedding_service = FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

    result = await hybrid_search(
        session=session,
        query=body.query,
        workspace_id=api_key.workspace_id,
        embedding_service=embedding_service,
        limit=body.limit,
        entity_types=body.entity_types,
    )

    if redis_client:
        await redis_client.aclose()

    return result
