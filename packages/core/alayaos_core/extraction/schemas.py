"""Pydantic schemas for LLM extraction output validation."""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    entity_type: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    external_ids: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        # Strip control chars (keep \t \n \r which are \x09 \x0a \x0d)
        v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)
        # XSS prevention
        if re.search(r"<\s*script", v, re.IGNORECASE):
            raise ValueError("Script tags not allowed in entity names")
        return v.strip()


class ExtractedRelation(BaseModel):
    source_entity: str = Field(min_length=1, max_length=500)
    target_entity: str = Field(min_length=1, max_length=500)
    relation_type: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class ExtractedClaim(BaseModel):
    entity: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=5000)
    value_type: str = "text"  # text, date, number, boolean, entity_ref
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    source_summary: str | None = None


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=100)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=200)
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=500)


class EntityMatchResult(BaseModel):
    """Used by LLM entity resolution (Tier 3)."""

    is_same_entity: bool
    reasoning: str = Field(max_length=200)
