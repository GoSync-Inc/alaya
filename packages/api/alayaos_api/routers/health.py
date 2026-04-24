"""Health check endpoints."""

from contextlib import suppress
from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_session
from alayaos_core.config import Settings

router = APIRouter(tags=["health"])


@lru_cache
def get_settings() -> Settings:
    return Settings()


async def _check_redis(redis_url) -> str:
    url = redis_url.get_secret_value() if hasattr(redis_url, "get_secret_value") else str(redis_url or "")
    if not url:
        return "degraded"

    client = None
    try:
        client = aioredis.from_url(url)
        return "ok" if await client.ping() else "degraded"
    except Exception:
        return "down"
    finally:
        if client is not None:
            with suppress(Exception):
                await client.aclose()


@router.get("/health/live")
async def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(session: Annotated[AsyncSession, Depends(get_session)]):
    settings = get_settings()
    checks = {}

    # Database
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    # Migrations (check Alembic head)
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar_one_or_none()
        checks["migrations"] = "ok" if version else "pending"
    except Exception:
        checks["migrations"] = "unavailable"

    # Seeds
    try:
        result = await session.execute(text("SELECT check_core_seeds()"))
        count = result.scalar_one()
        checks["seeds"] = "ok" if count > 0 else "missing"
    except Exception:
        checks["seeds"] = "unavailable"

    # Redis (non-blocking)
    checks["redis"] = await _check_redis(settings.REDIS_URL)

    # First run check
    try:
        result = await session.execute(text("SELECT check_user_api_keys()"))
        user_keys = result.scalar_one()
        first_run = user_keys == 0
    except Exception:
        first_run = True

    ok_checks = [v for v in checks.values() if v != "unavailable"]
    overall = "ok" if ok_checks and all(v == "ok" for v in ok_checks) else "degraded"

    if settings.HEALTH_READY_VERBOSE:
        return {"status": overall, "checks": checks, "first_run": first_run}
    return {"status": overall}
