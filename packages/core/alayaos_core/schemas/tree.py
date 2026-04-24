"""Tree node and briefing schemas."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


@dataclass(frozen=True, slots=True)
class TreeNodeView:
    """Tree endpoint DTO that prevents non-admin summary leaks."""

    id: uuid.UUID
    path: str
    workspace_id: uuid.UUID
    entity_id: uuid.UUID | None
    node_type: str
    is_dirty: bool
    last_rebuilt_at: datetime | None
    markdown_cache: str | None
    summary: dict | None


class TreeNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    node_type: str
    entity_id: uuid.UUID | None = None
    is_dirty: bool
    sort_order: int
    summary: dict
    markdown_cache: str | None = None
    last_rebuilt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TreeBriefing(BaseModel):
    """LLM-generated briefing for a tree node."""

    title: str
    summary: str
    key_facts: list[str]
    status: str | None = None
    last_updated: str | None = None


class TreePathRequest(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        if "//" in v:
            raise ValueError("Double slashes not allowed")
        if "\x00" in v or any(ord(c) < 32 for c in v):
            raise ValueError("Control characters not allowed")
        if len(v) > 512:
            raise ValueError("Path too long (max 512)")
        # Count depth
        parts = [p for p in v.split("/") if p]
        if len(parts) > 10:
            raise ValueError("Path too deep (max 10 levels)")
        return v


class TreeExportRequest(BaseModel):
    path: str = ""

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return TreePathRequest.validate_path(v) if v else v
