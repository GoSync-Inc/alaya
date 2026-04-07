"""Pydantic schema for PipelineTrace read endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PipelineTraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    event_id: uuid.UUID
    extraction_run_id: uuid.UUID | None
    stage: str
    decision: str
    reason: str | None
    details: dict | None
    tokens_used: int | None = 0
    cost_usd: float | None = 0.0
    duration_ms: int | None = 0
    created_at: datetime
