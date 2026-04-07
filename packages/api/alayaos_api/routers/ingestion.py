"""Ingestion endpoints — create L0 events and trigger extraction runs."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    get_workspace_session,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.event import EventRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.schemas.ingestion import IngestTextRequest, IngestTextResponse

router = APIRouter()


@router.post("/ingest/text", status_code=202)
async def ingest_text(
    body: IngestTextRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("write"))],
) -> IngestTextResponse:
    # Auto-generate source_id if not provided
    source_id = body.source_id if body.source_id is not None else str(uuid.uuid4())

    event_repo = EventRepository(session, api_key.workspace_id)
    event, _created = await event_repo.create_or_update(
        workspace_id=api_key.workspace_id,
        source_type=body.source_type,
        source_id=source_id,
        content={"text": body.text},
        metadata={
            "access_level": body.access_level,
            "event_kind": body.event_kind,
            "occurred_at": body.occurred_at.isoformat() if body.occurred_at else None,
            **body.metadata,
        },
    )

    run_repo = ExtractionRunRepository(session, api_key.workspace_id)
    run = await run_repo.create(
        workspace_id=api_key.workspace_id,
        event_id=event.id,
        status="pending",
    )

    return IngestTextResponse(
        event_id=event.id,
        extraction_run_id=run.id,
        status="pending",
    )
