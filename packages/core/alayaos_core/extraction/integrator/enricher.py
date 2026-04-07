"""EntityEnricher — LLM-powered batch enrichment for knowledge graph integration."""

from __future__ import annotations

import structlog

from alayaos_core.extraction.integrator.schemas import EnrichmentResult, EntityWithContext

log = structlog.get_logger()


def _build_enrichment_prompt(entities: list[EntityWithContext]) -> str:
    """Build a prompt string for the LLM enrichment call."""
    lines = ["Analyze the following entities and suggest enrichment actions:"]
    for e in entities:
        lines.append(f"- id={e.id} name={e.name!r} type={e.entity_type} aliases={e.aliases}")
        if e.claims:
            lines.append(f"  claims: {e.claims[:3]}")  # limit to first 3 for brevity
        if e.relations:
            lines.append(f"  relations: {e.relations[:3]}")
    return "\n".join(lines)


_SYSTEM_PROMPT = """You are a knowledge graph enrichment assistant.

Analyze the provided entities and suggest enrichment actions. Focus on:
1. Building relations: connect Tasks to Projects (add_relation), connect People to Teams (add_relation)
2. Type correction: fix misclassified entity types (update_type)
3. Status updates: identify completed or active statuses (update_status)
4. Assignee matching: link tasks to their responsible people (add_assignee)
5. Date normalization: standardize date formats in claims (normalize_date)
6. Noise removal: flag entities that look like system artifacts, hashes, or junk (remove_noise)

Return a list of enrichment actions. Each action must have:
- action: one of "add_relation" | "update_type" | "update_status" | "remove_noise" | "normalize_date" | "add_assignee"
- entity_id: UUID of the entity to act on (nullable)
- details: dict with action-specific parameters
"""


class EntityEnricher:
    """LLM-powered batch enrichment.

    Processes entities in batches of `batch_size`, calling the LLM once per batch
    to get enrichment actions for relation building, type correction, and noise removal.
    """

    def __init__(self, llm, batch_size: int = 20) -> None:
        self.llm = llm
        self.batch_size = batch_size

    async def enrich_batch(self, entities: list[EntityWithContext]) -> EnrichmentResult:
        """LLM-powered batch enrichment. Returns enrichment actions."""
        result = EnrichmentResult()
        if not entities:
            return result

        for i in range(0, len(entities), self.batch_size):
            batch = entities[i : i + self.batch_size]
            batch_result = await self._enrich_single_batch(batch)
            result.actions.extend(batch_result.actions)

        return result

    async def _enrich_single_batch(self, batch: list[EntityWithContext]) -> EnrichmentResult:
        """Call LLM for a single batch of entities."""
        prompt = _build_enrichment_prompt(batch)
        try:
            result, _usage = await self.llm.extract(
                text=prompt,
                system_prompt=_SYSTEM_PROMPT,
                response_model=EnrichmentResult,
                max_tokens=2048,
            )
            return result
        except Exception:
            log.warning("enricher_llm_call_failed", batch_size=len(batch))
            return EnrichmentResult()
