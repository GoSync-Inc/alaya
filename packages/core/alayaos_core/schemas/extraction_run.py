import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExtractionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    event_id: uuid.UUID | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    llm_provider: str | None
    llm_model: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    entities_created: int
    entities_merged: int
    relations_created: int
    claims_created: int
    claims_superseded: int
    resolver_decisions: list | None = None  # only included on detail view
    error_message: str | None
    parent_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
