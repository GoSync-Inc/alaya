"""Search and evidence bundle schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)
    entity_types: list[str] | None = None


class EvidenceUnit(BaseModel):
    source_type: Literal["entity", "claim", "chunk"]
    source_id: uuid.UUID
    content: str
    score: float
    channels: list[Literal["vector", "fts", "entity_name"]]
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    claim_id: uuid.UUID | None = None
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[EvidenceUnit]
    total: int
    channels_used: list[str]
    elapsed_ms: int
