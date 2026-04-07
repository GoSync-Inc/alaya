"""Ingestion endpoints — create L0 events and trigger extraction runs."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.event import EventRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.schemas.ingestion import IngestTextRequest, IngestTextResponse

router = APIRouter()

_MAX_TEXT_CHARS = 100_000


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

    # Idempotency: only create extraction run for new events
    run_repo = ExtractionRunRepository(session, api_key.workspace_id)
    if created:
        run = await run_repo.create(
            workspace_id=api_key.workspace_id,
            event_id=event.id,
            status="pending",
        )
    else:
        # Re-ingest: find existing pending run or create with parent_run_id
        existing_runs = await run_repo.list_by_event(event.id)
        pending = [r for r in existing_runs if r.status == "pending"]
        if pending:
            run = pending[0]
        else:
            # Create new run linked to previous
            completed = [r for r in existing_runs if r.status == "completed"]
            parent_id = completed[-1].id if completed else None
            run = await run_repo.create(
                workspace_id=api_key.workspace_id,
                event_id=event.id,
                status="pending",
                parent_run_id=parent_id,
            )

    # Enqueue extraction job (async, non-blocking)
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
