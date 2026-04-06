import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PredicateCreate(BaseModel):
    slug: str
    display_name: str
    value_type: str
    description: str | None = None
    domain_types: list[str] | None = None
    cardinality: str = "many"
    inverse_slug: str | None = None


class PredicateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    slug: str
    display_name: str
    description: str | None = None
    value_type: str
    domain_types: list[str] | None = None
    cardinality: str
    inverse_slug: str | None = None
    is_core: bool
    schema_version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
