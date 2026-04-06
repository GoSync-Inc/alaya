import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkspaceCreate(BaseModel):
    name: str
    slug: str


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    settings: dict
    created_at: datetime
    updated_at: datetime


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None
