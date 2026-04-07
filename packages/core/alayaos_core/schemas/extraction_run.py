import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExtractionRunListRead(BaseModel):
    """List view — excludes resolver_decisions for performance."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    event_id: uuid.UUID | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    llm_provider: str | None
    llm_model: str | None
    prompt_version: str | None = None
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0
    cost_usd: float
    entities_created: int
    entities_merged: int
    relations_created: int
    claims_created: int
    claims_superseded: int
    error_message: str | None
    parent_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    chunks_total: int = 0
    chunks_crystal: int = 0
    chunks_skipped: int = 0
    cortex_cost_usd: float = 0.0
    crystallizer_cost_usd: float = 0.0
    verification_changes: int = 0


class ExtractionRunRead(ExtractionRunListRead):
    """Detail view — includes resolver_decisions."""

    resolver_decisions: list | None = None
