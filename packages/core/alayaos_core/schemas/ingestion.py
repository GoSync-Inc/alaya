import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IngestTextRequest(BaseModel):
    text: str = Field(min_length=1)
    source_type: str = "manual"
    source_id: str | None = None  # auto-generated UUID if not provided
    access_level: str = "public"
    event_kind: str | None = None
    occurred_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class IngestTextResponse(BaseModel):
    event_id: uuid.UUID
    extraction_run_id: uuid.UUID
    status: str = "pending"
