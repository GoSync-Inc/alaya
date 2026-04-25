"""Pydantic schemas for the Integrator Engine."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from alayaos_core.llm.interface import LLMUsage


class MergeGroup(BaseModel):
    """A group of duplicate entities identified by the LLM batch deduplicator.

    winner_id  — entity to keep (gets merged_name, merged_description, union aliases)
    loser_ids  — entities to soft-delete and reassign claims/relations from
    """

    winner_id: uuid.UUID
    loser_ids: list[uuid.UUID]
    merged_name: str
    merged_description: str
    merged_aliases: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=280)


class DedupResult(BaseModel):
    """Result from a batch LLM deduplication call."""

    groups: list[MergeGroup] = Field(default_factory=list)


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
    reasoning: str = Field(default="", max_length=1000)


class IntegratorPhaseUsage(BaseModel):
    """Per-phase cost and timing captured during an integrator run."""

    stage: Literal["integrator:panoramic", "integrator:dedup", "integrator:enricher"]
    pass_number: int = 1
    usage: LLMUsage
    duration_ms: int
    details: dict = Field(default_factory=dict)


class IntegratorRunResult(BaseModel):
    """Summary of a completed integrator run."""

    status: Literal["completed", "failed", "skipped"] = "completed"
    reason: str | None = None
    error_message: str | None = None
    entities_scanned: int = 0
    entities_deduplicated: int = 0
    entities_enriched: int = 0
    relations_created: int = 0
    claims_updated: int = 0
    noise_removed: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    pass_count: int = 1
    convergence_reason: str | None = None
    phase_usages: list[IntegratorPhaseUsage] = Field(default_factory=list)
