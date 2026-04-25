"""EntityEnricher — LLM-powered batch enrichment for knowledge graph integration."""

from __future__ import annotations

import structlog

from alayaos_core.extraction.integrator.schemas import EnrichmentResult, EntityWithContext
from alayaos_core.llm.interface import LLMUsage

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

    async def enrich_batch(self, entities: list[EntityWithContext]) -> tuple[EnrichmentResult, LLMUsage]:
        """LLM-powered batch enrichment. Returns (enrichment_result, aggregated_llm_usage).

        Exceptions from llm.extract() propagate to the caller (engine's begin_nested savepoint).
        """
        result = EnrichmentResult()
        agg_tokens_in = 0
        agg_tokens_out = 0
        agg_tokens_cached = 0
        agg_cache_write_5m = 0
        agg_cache_write_1h = 0
        agg_cost_usd = 0.0
        if not entities:
            return result, LLMUsage(
                tokens_in=0,
                tokens_out=0,
                tokens_cached=0,
                cache_write_5m_tokens=0,
                cache_write_1h_tokens=0,
                cost_usd=0.0,
            )

        for i in range(0, len(entities), self.batch_size):
            batch = entities[i : i + self.batch_size]
            batch_result, batch_usage = await self._enrich_single_batch(batch)
            result.actions.extend(batch_result.actions)
            # Accumulate token usage (TTL buckets summed independently)
            agg_tokens_in += batch_usage.tokens_in
            agg_tokens_out += batch_usage.tokens_out
            agg_tokens_cached += batch_usage.tokens_cached
            agg_cache_write_5m += batch_usage.cache_write_5m_tokens
            agg_cache_write_1h += batch_usage.cache_write_1h_tokens
            agg_cost_usd += batch_usage.cost_usd

        return result, LLMUsage(
            tokens_in=agg_tokens_in,
            tokens_out=agg_tokens_out,
            tokens_cached=agg_tokens_cached,
            cache_write_5m_tokens=agg_cache_write_5m,
            cache_write_1h_tokens=agg_cache_write_1h,
            cost_usd=agg_cost_usd,
        )

    async def _enrich_single_batch(self, batch: list[EntityWithContext]) -> tuple[EnrichmentResult, LLMUsage]:
        """Call LLM for a single batch of entities.

        Exceptions propagate to the caller (engine's begin_nested savepoint per charter Pattern A).
        """
        prompt = _build_enrichment_prompt(batch)
        result, usage = await self.llm.extract(
            text=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_model=EnrichmentResult,
            max_tokens=2048,
            stage="integrator:enricher",
        )
        return result, usage
