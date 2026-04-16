"""CrystallizerExtractor — entity extraction from crystal L0Chunks."""

from __future__ import annotations

import uuid
from datetime import date
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

        # Current date injection
        prompt += f"Current date: {date.today().isoformat()}\n\n"

        # Bilingual instruction
        prompt += (
            "## Language\n"
            "Text may be in Russian, English, or a mix. Extract entity names in the ORIGINAL language used in the text. Do not translate names.\n\n"
        )

        # Hierarchy vocabulary with time-horizons
        prompt += (
            "## Entity Types (use these EXACTLY)\n"
            "- task (tier 1): A daily/weekly work item — things people DO this sprint\n"
            "- project (tier 2): A 1-week to 1-month initiative composed of tasks\n"
            "- goal (tier 3): A quarterly/monthly objective composed of projects\n"
            "- north_star (tier 4): A yearly to multi-year strategic objective\n"
            "- person: An individual human\n"
            "- team: A group of people or organization/company\n"
            "- document: A written artifact (report, spec, RFC, wiki page)\n"
            "- decision: A resolved choice with consequences\n"
            "- meeting: A scheduled gathering of people\n"
            '- topic: A discussion theme that is NOT actionable work (use "task" for actionable items)\n'
            "- tool: A software product, service, or technology\n"
            "- process: A repeatable workflow or procedure\n"
            "- event: A one-time occurrence (concert, conference, incident)\n"
        )
        if entity_types:
            prompt += "\n### Additional workspace entity types\n"
            prompt += (
                "\n".join(f"- {et.get('name', et.get('slug', ''))}: {et.get('description', '')}" for et in entity_types)
                + "\n"
            )
        prompt += "\n"

        # Type-discrimination examples — Cyrillic strings are intentional prompt content (noqa: RUF001)
        prompt += "## Examples for type discrimination\n"
        prompt += '- "Checkpoint Scanner 2.13.0" \u2192 type=project (a software release/version), NOT event\n'
        prompt += '- "\u041c\u0422\u0421" \u2192 type=team (a company/organization), NOT person\n'
        prompt += '- "\u0411\u0430\u0433: \u043d\u0435 \u043e\u0431\u043d\u043e\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u0441\u043f\u0438\u0441\u043e\u043a \u0441\u043e\u0431\u044b\u0442\u0438\u0439" \u2192 type=task (a work item to fix), NOT topic\n'
        prompt += '- "\u0424\u0438\u0447\u0430 \u0441\u043e\u0433\u043b\u0430\u0441\u0438\u044f \u0432 \u041b\u041a" \u2192 type=task (feature work being built), NOT topic\n'
        prompt += '- "\u041f\u0435\u0440\u0432\u044b\u0439 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u043d\u044b\u0439 \u0431\u0430\u0433" \u2192 type=event (historical anecdote), NOT task\n'
        prompt += '- "\u0421\u0435\u0440\u0434\u0446\u0435" (song title) \u2192 type=event or topic, NOT person\n'
        prompt += '- "\u0410\u0434\u0440\u0435\u0441\u0430\u0442 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f" (generic noun) \u2192 DO NOT extract (too vague, not a real entity)\n\n'

        # Name length guidance
        prompt += "## Name length\n"
        prompt += 'Keep entity names under 50 characters. If a concept needs more text, put the short form in "name" and the full description in "description".\n'
        prompt += "Example:\n"
        prompt += '  name: "\u0411\u0430\u0433 \u0432\u043e\u0437\u0432\u0440\u0430\u0442\u0430 \u0438\u0437 \u043e\u0431\u043b\u0430\u0447\u043d\u043e\u0439 \u043a\u0430\u0441\u0441\u044b"  (30 chars)\n'
        prompt += '  description: "\u041d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0442\u044c \u0431\u0430\u043b\u0430\u043d\u0441 \u043e\u0440\u0433\u0430\u043d\u0438\u0437\u0430\u0442\u043e\u0440\u0430 \u043f\u0440\u0438 \u0432\u043e\u0437\u0432\u0440\u0430\u0442\u0435 \u0437\u0430\u043a\u0430\u0437\u0430 \u0438\u0437 \u043e\u0431\u043b\u0430\u0447\u043d\u043e\u0439 \u043a\u0430\u0441\u0441\u044b"\n\n'

        # Predicates — always include part_of
        predicate_names = [p.get("name", p.get("slug", "")) for p in predicates]
        if "part_of" not in predicate_names:
            predicate_names = ["part_of", *predicate_names]
        prompt += "## Predicates\n"
        prompt += "\n".join(f"- {name}" for name in predicate_names) + "\n\n"

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
