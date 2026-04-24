"""Pydantic schemas for IntegratorAction."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IntegratorActionCreate(BaseModel):
    run_id: uuid.UUID
    pass_number: int = 1
    action_type: str
    entity_id: uuid.UUID | None = None
    params: dict = {}
    targets: list = []
    inverse: dict = {}
    trace_id: uuid.UUID | None = None
    model_id: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    snapshot_schema_version: int = 1


class IntegratorActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: uuid.UUID
    pass_number: int
    action_type: str
    status: str
    entity_id: uuid.UUID | None
    params: dict
    targets: list
    inverse: dict
    trace_id: uuid.UUID | None
    model_id: str | None
    confidence: float | None
    rationale: str | None
    snapshot_schema_version: int
    created_at: datetime
    applied_at: datetime | None
    reverted_at: datetime | None
    reverted_by: uuid.UUID | None


class IntegratorActionRollbackResponse(BaseModel):
    reverted_action_id: uuid.UUID
    conflicts: list[str]
