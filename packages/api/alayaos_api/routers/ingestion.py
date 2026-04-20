"""Ingestion endpoints — create L0 events and trigger extraction runs."""

import contextlib
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    require_scope,
)
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.event import EventRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.schemas.ingestion import IngestTextRequest, IngestTextResponse
from alayaos_core.services.rate_limiter import RateLimiterService

router = APIRouter()

_MAX_TEXT_CHARS = 100_000


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


async def _check_ingest_rate_limit(
    settings: Settings,
    api_key: APIKey,
) -> None:
    """Enforce the per-key ingest limit; raises 429/503 on decision.

    Only called when an ingest would cause **new** extraction work
    (either a new L0 event or a new extraction run on an existing one).
    Idempotent retries that hit an already-pending run do not consume
    a slot — otherwise transient client retries would burn budget
    without any LLM cost being incurred downstream.
    """
    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL.get_secret_value())
    try:
        limiter = RateLimiterService(redis=redis_client)
        decision = await limiter.check(
            f"{api_key.key_prefix}:ingest",
            settings.INGEST_RATE_LIMIT_PER_MINUTE,
            60,
        )
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
    finally:
        if redis_client:
            await redis_client.aclose()


@router.post("/ingest/text", status_code=202)
async def ingest_text(
    body: IngestTextRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
):
    # Explicit text length validation with spec-defined error code
    if len(body.text) > _MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "validation.text_too_long",
                    "message": f"Text exceeds maximum length of {_MAX_TEXT_CHARS} characters.",
                    "hint": "Split into smaller chunks or use batch ingestion.",
                    "docs": None,
                    "request_id": None,
                }
            },
        )

    settings = Settings()

    # Auto-generate source_id if not provided
    source_id = body.source_id if body.source_id is not None else str(uuid.uuid4())

    event_repo = EventRepository(session, api_key.workspace_id)
    event, created = await event_repo.create_or_update(
        workspace_id=api_key.workspace_id,
        source_type=body.source_type,
        source_id=source_id,
        content={"text": body.text},
        metadata=body.metadata,
        raw_text=body.text,
        access_level=body.access_level,
        event_kind=body.event_kind,
        occurred_at=body.occurred_at,
    )

    # Idempotency: only create extraction run for new events.
    # ``enqueued`` tracks whether this request actually produces new
    # extraction work — used to gate both the rate-limiter and the
    # task-queue enqueue so retries against a pending run cannot
    # (a) skip the budget cap while (b) spamming duplicate LLM work.
    run_repo = ExtractionRunRepository(session, api_key.workspace_id)
    enqueued = False
    if created:
        # New event → new extraction → rate-limited (LLM cost gate).
        await _check_ingest_rate_limit(settings, api_key)
        run = await run_repo.create(
            workspace_id=api_key.workspace_id,
            event_id=event.id,
            status="pending",
        )
        enqueued = True
    else:
        # Re-ingest: find existing pending run or create with parent_run_id
        existing_runs = await run_repo.list_by_event(event.id)
        pending = [r for r in existing_runs if r.status == "pending"]
        if pending:
            # Fully idempotent path — no LLM cost, no slot consumed,
            # and no re-enqueue (existing worker will pick up the run).
            run = pending[0]
        else:
            # Re-extract of an existing event = fresh extraction → rate-limited.
            await _check_ingest_rate_limit(settings, api_key)
            completed = [r for r in existing_runs if r.status == "completed"]
            parent_id = completed[-1].id if completed else None
            run = await run_repo.create(
                workspace_id=api_key.workspace_id,
                event_id=event.id,
                status="pending",
                parent_run_id=parent_id,
            )
            enqueued = True

    # Only enqueue when this request produced new extraction work.
    # Idempotent retries hitting an already-pending run fall through
    # untouched — no duplicate kiq(), no duplicate LLM spend.
    if enqueued:
        try:
            from alayaos_core.worker.tasks import job_extract

            await job_extract.kiq(str(event.id), str(run.id), str(api_key.workspace_id))
        except Exception:
            pass  # Worker may not be running; run stays pending for manual pickup

    return data_response(
        IngestTextResponse(
            event_id=event.id,
            extraction_run_id=run.id,
            status=run.status,
        )
    )
