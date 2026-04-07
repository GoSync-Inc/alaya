"""Pydantic schemas for the Integrator Engine."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class EntityWithContext(BaseModel):
    """Entity with its associated claims, relations, and metadata for integrator processing."""

    id: uuid.UUID
    name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    properties: dict = Field(default_factory=dict)
    claims: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


class DuplicatePair(BaseModel):
    """A detected pair of potentially duplicate entities."""

    entity_a_id: uuid.UUID
    entity_b_id: uuid.UUID
    entity_a_name: str
    entity_b_name: str
    score: float
    method: str  # "fuzzy" | "transliteration" | "llm"


class EnrichmentAction(BaseModel):
    """A single enrichment action proposed by the Enricher."""

    action: str  # "add_relation" | "update_type" | "update_status" | "remove_noise" | "normalize_date" | "add_assignee"
    entity_id: uuid.UUID | None = None
    details: dict = Field(default_factory=dict)


class EnrichmentResult(BaseModel):
    """Result of a batch enrichment pass."""

    actions: list[EnrichmentAction] = Field(default_factory=list)


class EntityMatchResult(BaseModel):
    """Used by the Integrator LLM for dedup disambiguation."""

    is_same_entity: bool
    reasoning: str = Field(default="", max_length=500)


class IntegratorRunResult(BaseModel):
    """Summary of a completed integrator run."""

    status: str  # "completed" | "skipped" | "failed"
    reason: str | None = None
    entities_scanned: int = 0
    entities_deduplicated: int = 0
    entities_enriched: int = 0
    relations_created: int = 0
    claims_updated: int = 0
    noise_removed: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
