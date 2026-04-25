"""Pydantic schema for PipelineTrace read endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PipelineTraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    event_id: uuid.UUID | None
    extraction_run_id: uuid.UUID | None
    integrator_run_id: uuid.UUID | None = None
    stage: str
    decision: str
    reason: str | None
    details: dict | None
    tokens_used: int | None = 0
    # Granular token-class columns (migration 009)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    cost_usd: float | None = 0.0
    duration_ms: int | None = 0
    created_at: datetime
