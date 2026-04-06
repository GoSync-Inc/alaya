import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    source_type: str
    source_id: str
    content: dict
    metadata: dict | None = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    source_type: str
    source_id: str
    content: dict
    content_hash: str | None = None
    event_metadata: dict = {}
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EventUpdate(BaseModel):
    content: dict | None = None
    metadata: dict | None = None
    processed_at: datetime | None = None
