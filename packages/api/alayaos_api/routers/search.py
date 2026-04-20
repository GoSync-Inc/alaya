"""Search endpoint."""

import contextlib
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_workspace_session, require_scope
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.schemas.search import SearchRequest, SearchResponse
from alayaos_core.services.rate_limiter import RateLimiterService
from alayaos_core.services.search import hybrid_search

router = APIRouter()


def _rate_limit_error(code: str, message: str, hint: str | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "docs": None,
            "request_id": None,
        }
    }


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    settings = Settings()

    # Rate limiting
    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL.get_secret_value())
    try:
        limiter = RateLimiterService(redis=redis_client)
        decision = await limiter.check(f"{api_key.key_prefix}:search", 60, 60)
        if not decision.backend_available:
            raise HTTPException(
                status_code=503,
                detail=_rate_limit_error(
                    "server.rate_limit_unavailable",
                    "Rate limiting backend is unavailable.",
                    "Retry later.",
                ),
            )
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail=_rate_limit_error("rate_limit.exceeded", "Rate limit exceeded.", "Retry later."),
                headers={"Retry-After": str(decision.retry_after or 60)},
            )

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

        return result
    finally:
        if redis_client:
            await redis_client.aclose()
