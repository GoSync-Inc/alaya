import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExternalIdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    external_id: str


class EntityCreate(BaseModel):
    entity_type_id: uuid.UUID
    name: str
    description: str | None = None
    properties: dict | None = None


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    entity_type_id: uuid.UUID
    name: str
    description: str | None = None
    properties: dict | None = None
    is_deleted: bool = False
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    external_ids: list[ExternalIdRead] = []
    created_at: datetime
    updated_at: datetime


class EntityUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    properties: dict | None = None
    is_deleted: bool | None = None
