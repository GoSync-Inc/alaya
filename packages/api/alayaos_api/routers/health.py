"""Health check endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_session

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(session: Annotated[AsyncSession, Depends(get_session)]):
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
        result = await session.execute(text("SELECT COUNT(*) FROM entity_type_definitions WHERE is_core = true"))
        count = result.scalar_one()
        checks["seeds"] = "ok" if count > 0 else "missing"
    except Exception:
        checks["seeds"] = "unavailable"

    # Redis (non-blocking)
    checks["redis"] = "unavailable"  # TODO: add redis check when redis is integrated

    # First run check
    try:
        result = await session.execute(text("SELECT COUNT(*) FROM api_keys WHERE is_bootstrap = false"))
        user_keys = result.scalar_one()
        first_run = user_keys == 0
    except Exception:
        first_run = True

    overall = "ok" if all(v == "ok" for v in checks.values() if v != "unavailable") else "degraded"

    return {"status": overall, "checks": checks, "first_run": first_run}
