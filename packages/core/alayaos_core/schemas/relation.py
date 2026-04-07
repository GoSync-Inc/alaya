import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RelationCreate(BaseModel):
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_type: str
    confidence: float = 1.0


class RelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_type: str
    confidence: float
    extraction_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
