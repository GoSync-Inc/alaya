"""PipelineTrace endpoints (nested under events)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    get_workspace_session,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.pipeline_trace import PipelineTraceRepository
from alayaos_core.schemas.pipeline_trace import PipelineTraceRead

router = APIRouter()


@router.get("/events/{event_id}/trace")
async def list_event_traces(
    event_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = PipelineTraceRepository(session, api_key.workspace_id)
    traces = await repo.list_by_event(event_id)
    items = [PipelineTraceRead.model_validate(t) for t in traces]
    return {"data": items, "meta": {"count": len(items)}}
