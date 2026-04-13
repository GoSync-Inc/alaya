"""Ask (Q&A) endpoint."""

import contextlib
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_workspace_session, require_scope
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.services.ask import AskResult, ask
from alayaos_core.services.rate_limiter import RateLimiterService

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=20)


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


@router.post("/ask", response_model=AskResult)
async def ask_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    settings = Settings()

    # Rate limiting: 10/min per key for /ask
    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL)
    try:
        limiter = RateLimiterService(redis=redis_client)
        decision = await limiter.check(f"{api_key.key_prefix}:ask", settings.ASK_RATE_LIMIT_PER_MINUTE, 60)
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

        if settings.ANTHROPIC_API_KEY.get_secret_value():
            from alayaos_core.llm.anthropic import AnthropicAdapter

            llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.ASK_MODEL)
        else:
            from alayaos_core.llm.fake import FakeLLMAdapter

            llm = FakeLLMAdapter()

        embedding_service = None
        if settings.FEATURE_FLAG_VECTOR_SEARCH:
            from alayaos_core.services.embedding import FastEmbedService

            embedding_service = FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

        return await ask(
            session=session,
            question=body.question,
            workspace_id=api_key.workspace_id,
            llm=llm,
            embedding_service=embedding_service,
            max_results=body.max_results,
        )
    finally:
        if redis_client:
            await redis_client.aclose()
