import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClaimCreate(BaseModel):
    entity_id: uuid.UUID
    predicate: str
    predicate_id: uuid.UUID | None = None
    value: dict
    value_type: str = "text"
    confidence: float = 1.0
    observed_at: datetime | None = None
    source_event_id: uuid.UUID | None = None
    source_summary: str | None = None


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    entity_id: uuid.UUID
    predicate: str
    predicate_id: uuid.UUID | None
    value: dict
    value_type: str
    confidence: float
    status: str
    observed_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    supersedes: uuid.UUID | None
    source_event_id: uuid.UUID | None
    source_summary: str | None
    extraction_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ClaimUpdate(BaseModel):
    status: str | None = None  # valid transitions: active→retracted, active→disputed
