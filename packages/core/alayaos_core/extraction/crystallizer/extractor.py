"""CrystallizerExtractor — entity extraction from crystal L0Chunks."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from alayaos_core.extraction.schemas import ExtractionResult

if TYPE_CHECKING:
    from alayaos_core.llm.interface import LLMServiceInterface, LLMUsage
    from alayaos_core.models.chunk import L0Chunk
    from alayaos_core.services.entity_cache import EntityCacheService

# Domain → relevant entity types for cache snapshot filtering
_DOMAIN_TO_TYPES: dict[str, list[str]] = {
    "project": ["project", "task", "milestone"],
    "decision": ["decision", "meeting"],
    "strategic": ["project", "goal"],
    "risk": ["risk", "issue"],
    "people": ["person", "team"],
    "engineering": ["document", "project"],
    "knowledge": ["document", "process"],
    "customer": ["person", "organization"],
    "smalltalk": [],
}


def apply_confidence_tiers(result: ExtractionResult, high: float = 0.9, low: float = 0.5) -> ExtractionResult:
    """Assign tier labels ('high'/'medium'/'low') to each extracted entity based on confidence."""
    for entity in result.entities:
        if entity.confidence >= high:
            entity.tier = "high"
        elif entity.confidence >= low:
            entity.tier = "medium"
        else:
            entity.tier = "low"
    return result


class CrystallizerExtractor:
    def __init__(self, llm: LLMServiceInterface, entity_cache: EntityCacheService) -> None:
        self.llm = llm
        self.entity_cache = entity_cache

    async def extract(
        self,
        chunk: L0Chunk,
        entity_types: list[dict],
        predicates: list[dict],
        workspace_id: uuid.UUID,
    ) -> tuple[ExtractionResult, LLMUsage]:
        """Extract entities, relations, and claims from a crystal chunk."""
        # 1. Get entity snapshot for prompt injection
        snapshot = await self.entity_cache.get_snapshot(
            workspace_id,
            types=self._relevant_types(chunk.domain_scores or {}),
            limit=100,
        )
        # 2. Build system prompt
        system_prompt = self._build_prompt(entity_types, predicates, snapshot, chunk)
        # 3. LLM extract
        result, usage = await self.llm.extract(chunk.text, system_prompt, ExtractionResult)
        # 4. Validate: reject garbage entities
        result = self._validate(result)
        return result, usage

    def _relevant_types(self, domain_scores: dict) -> list[str] | None:
        """Map domain scores to relevant entity types. Returns None = all types."""
        types: set[str] = set()
        for domain, score in domain_scores.items():
            if score >= 0.2:
                types.update(_DOMAIN_TO_TYPES.get(domain, []))
        return list(types) if types else None

    def _build_prompt(
        self,
        entity_types: list[dict],
        predicates: list[dict],
        snapshot: list[dict],
        chunk: L0Chunk,
    ) -> str:
        """Build system prompt with entity types, predicates, domain context, and known entities."""
        prompt = "You are an entity extraction system for a corporate knowledge base.\n\n"
        prompt += "## Entity Types\n"
        prompt += (
            "\n".join(f"- {et.get('name', et.get('slug', ''))}: {et.get('description', '')}" for et in entity_types)
            + "\n\n"
        )
        prompt += "## Predicates\n"
        prompt += "\n".join(f"- {p.get('name', p.get('slug', ''))}" for p in predicates) + "\n\n"
        if snapshot:
            prompt += "## Known Entities (from previous extractions)\n"
            prompt += "\n".join(f"- {e['name']} ({e['entity_type']})" for e in snapshot[:50]) + "\n\n"
        prompt += f"## Domain Context\nPrimary domain: {chunk.primary_domain}\n"
        prompt += (
            "Domain scores: "
            + ", ".join(f"{k}={v:.1f}" for k, v in (chunk.domain_scores or {}).items() if v > 0.1)
            + "\n\n"
        )
        prompt += "Extract entities, relations, and claims from the following text. Match against known entities when possible. Return valid JSON."
        return prompt

    def _validate(self, result: ExtractionResult) -> ExtractionResult:
        """Post-extraction validation: reject garbage entities."""
        valid_entities = []
        for entity in result.entities:
            # Reject names longer than 12 words
            if len(entity.name.split()) > 12:
                continue
            # Reject questions-as-entities
            if entity.name.endswith("?"):
                continue
            valid_entities.append(entity)
        result.entities = valid_entities
        return result
