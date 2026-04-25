"""Pydantic schemas for IntegratorRun."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class IntegratorRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    trigger: str
    scope_description: str | None
    entities_scanned: int | None = 0
    entities_deduplicated: int | None = 0
    entities_enriched: int | None = 0
    relations_created: int | None = 0
    claims_updated: int | None = 0
    noise_removed: int | None = 0
    llm_model: str | None
    tokens_used: int | None = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    cost_usd: float | None = 0.0
    duration_ms: int | None = 0
    pass_count: int | None = 1
    convergence_reason: str | None = None
    status: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None

    @field_validator(
        "tokens_in", "tokens_out", "tokens_cached", "cache_write_5m_tokens", "cache_write_1h_tokens", mode="before"
    )
    @classmethod
    def _none_to_zero_int(cls, v: int | None) -> int:
        return v if v is not None else 0
