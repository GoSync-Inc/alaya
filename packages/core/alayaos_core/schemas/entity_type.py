import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityTypeCreate(BaseModel):
    slug: str
    display_name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None


class EntityTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    slug: str
    display_name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_core: bool
    schema_version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EntityTypeUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_active: bool | None = None
