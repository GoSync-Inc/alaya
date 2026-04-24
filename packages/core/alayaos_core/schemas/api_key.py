import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Scope = Literal["read", "write", "admin"]


class APIKeyCreate(BaseModel):
    name: str
    scopes: list[Scope] | None = None
    expires_at: datetime | None = None


class APIKeyRead(BaseModel):
    """Read schema — NEVER exposes key_hash or raw key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    is_bootstrap: bool
    created_at: datetime
    updated_at: datetime


class APIKeyCreateResponse(APIKeyRead):
    """Returned once on creation — includes the raw key shown only once."""

    raw_key: str
