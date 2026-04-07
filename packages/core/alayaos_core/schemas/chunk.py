"""Pydantic schema for L0Chunk read endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    event_id: uuid.UUID
    chunk_index: int
    chunk_total: int
    text: str
    token_count: int
    source_type: str
    source_id: str | None
    domain_scores: dict
    primary_domain: str | None
    is_crystal: bool | None
    classification_model: str | None
    classification_verified: bool | None
    verification_changed: bool | None
    processing_stage: str
    error_count: int | None = 0
    error_message: str | None
    extraction_run_id: uuid.UUID | None
    created_at: datetime
