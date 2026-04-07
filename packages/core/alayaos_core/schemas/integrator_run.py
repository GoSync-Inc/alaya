"""Pydantic schemas for IntegratorRun."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IntegratorRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    trigger: str
    scope_description: str | None
    entities_scanned: int | None = 0
    entities_deduplicated: int | None = 0
    entities_enriched: int | None = 0
    relations_created: int | None = 0
    claims_updated: int | None = 0
    noise_removed: int | None = 0
    llm_model: str | None
    tokens_used: int | None = 0
    cost_usd: float | None = 0.0
    duration_ms: int | None = 0
    status: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
