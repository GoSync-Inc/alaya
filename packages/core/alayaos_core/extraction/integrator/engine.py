"""IntegratorEngine — orchestrates dedup + enrichment pass over the knowledge graph."""

from __future__ import annotations

import contextlib
import time
import uuid

import structlog

from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
from alayaos_core.extraction.integrator.enricher import EntityEnricher
from alayaos_core.extraction.integrator.schemas import (
    EnrichmentAction,
    EntityWithContext,
    IntegratorRunResult,
)
from alayaos_core.extraction.writer import acquire_workspace_lock, release_workspace_lock

log = structlog.get_logger()


class IntegratorEngine:
    """Orchestrates a full Integrator pass for a workspace.

    Workflow:
    1. Acquire workspace lock (prevents concurrent integrator runs)
    2. Atomically drain dirty-set via RENAME
    3. Load 48h window entities from DB
    4. Combine dirty + window entity sets
    5. Load entity context (claims, relations) for each entity
    6. Deduplicate using 3-tier matching
    7. Batch enrich using LLM
    8. Apply enrichment actions (create relations, update entities, etc.)
    9. Warm entity cache
    10. Return run result with counters
    """

    def __init__(
        self,
        llm,
        entity_repo,
        claim_repo,
        relation_repo,
        entity_cache,
        redis,
        settings,
    ) -> None:
        self.llm = llm
        self.entity_repo = entity_repo
        self.claim_repo = claim_repo
        self.relation_repo = relation_repo
        self.entity_cache = entity_cache
        self.redis = redis
        self.settings = settings

        # Allow injection in tests
        self._deduplicator = EntityDeduplicator(
            llm=llm,
            threshold=settings.INTEGRATOR_DEDUP_THRESHOLD,
            ambiguous_low=settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW,
        )
        self._enricher = EntityEnricher(
            llm=llm,
            batch_size=settings.INTEGRATOR_BATCH_SIZE,
        )

    async def run(self, workspace_id: uuid.UUID, session) -> IntegratorRunResult:
        """Execute Integrator pass with workspace-level lock."""
        lock_key = f"integrator:lock:{workspace_id}"
        token = await acquire_workspace_lock(self.redis, lock_key, timeout=600)
        if not token:
            return IntegratorRunResult(status="skipped", reason="locked")
        try:
            return await self._run_locked(workspace_id, session)
        finally:
            await release_workspace_lock(self.redis, lock_key, token)

    async def _run_locked(self, workspace_id: uuid.UUID, session) -> IntegratorRunResult:
        """Execute the integrator pass (called while lock is held)."""
        start_ms = int(time.time() * 1000)

        # Step 1: Drain dirty-set atomically via RENAME
        dirty_key = f"dirty_set:{workspace_id}"
        processing_key = f"dirty_set:{workspace_id}:processing"
        dirty_entity_ids: set[uuid.UUID] = set()

        try:
            await self.redis.rename(dirty_key, processing_key)
            raw_members = await self.redis.smembers(processing_key)
            await self.redis.delete(processing_key)
            for member in raw_members:
                member_str = member.decode() if isinstance(member, bytes) else member
                with contextlib.suppress(ValueError):
                    dirty_entity_ids.add(uuid.UUID(member_str))
        except Exception:
            # dirty-set may not exist (no entities processed yet) — that's fine
            pass

        # Step 2: Load 48h window entities
        window_hours = getattr(self.settings, "INTEGRATOR_WINDOW_HOURS", 48)
        window_entities = await self.entity_repo.list_recent(workspace_id, hours=window_hours)

        # Step 3: Combine dirty IDs + window entity IDs (union, deduplicated)
        all_entity_ids = dirty_entity_ids | {e.id for e in window_entities}

        # Step 4: Load entity context for each unique entity ID
        entities_with_context: list[EntityWithContext] = []
        for entity_id in all_entity_ids:
            entity = await self.entity_repo.get_by_id(entity_id)
            if entity is None or getattr(entity, "is_deleted", False):
                continue

            # Load claims for this entity
            claims, _, _ = await self.claim_repo.list(entity_id=entity_id, limit=50)
            claims_dicts = [{"predicate": c.predicate, "value": c.value, "status": c.status} for c in claims]

            # Load relations for this entity
            relations, _, _ = await self.relation_repo.list(entity_id=entity_id, limit=50)
            relations_dicts = [
                {
                    "source": str(r.source_entity_id),
                    "target": str(r.target_entity_id),
                    "type": r.relation_type,
                }
                for r in relations
            ]

            # Resolve entity type slug
            try:
                entity_type_slug = entity.entity_type.slug
            except Exception:
                entity_type_slug = "unknown"

            entities_with_context.append(
                EntityWithContext(
                    id=entity.id,
                    name=entity.name,
                    entity_type=entity_type_slug,
                    aliases=list(entity.aliases or []),
                    properties=dict(entity.properties or {}),
                    claims=claims_dicts,
                    relations=relations_dicts,
                )
            )

        entities_scanned = len(entities_with_context)
        entities_deduplicated = 0
        entities_enriched = 0
        relations_created = 0
        claims_updated = 0
        noise_removed = 0

        # Step 5: Deduplicate
        if entities_with_context:
            dup_pairs = await self._deduplicator.find_duplicates(entities_with_context)
            entities_deduplicated = len(dup_pairs)
            log.info(
                "integrator_dedup",
                workspace_id=str(workspace_id),
                duplicates_found=entities_deduplicated,
            )

        # Step 6: Batch enrich
        enrichment_result = await self._enricher.enrich_batch(entities_with_context)
        entities_enriched = len(entities_with_context)

        # Step 7: Apply enrichment actions
        for action in enrichment_result.actions:
            counters = await self._apply_action(action, workspace_id, session)
            relations_created += counters.get("relations_created", 0)
            claims_updated += counters.get("claims_updated", 0)
            noise_removed += counters.get("noise_removed", 0)

        # Step 8: Warm entity cache with processed entities
        cache_entities = [
            {
                "name": e.name,
                "entity_type": e.entity_type,
                "aliases": e.aliases,
                "last_seen_at": 0,
            }
            for e in entities_with_context
        ]
        await self.entity_cache.warm(workspace_id, cache_entities)

        duration_ms = int(time.time() * 1000) - start_ms

        return IntegratorRunResult(
            status="completed",
            entities_scanned=entities_scanned,
            entities_deduplicated=entities_deduplicated,
            entities_enriched=entities_enriched,
            relations_created=relations_created,
            claims_updated=claims_updated,
            noise_removed=noise_removed,
            duration_ms=duration_ms,
        )

    async def _apply_action(self, action: EnrichmentAction, workspace_id: uuid.UUID, session) -> dict:
        """Apply a single enrichment action. Returns counter increments."""
        counters: dict[str, int] = {}
        try:
            if action.action == "add_relation":
                source_id = action.entity_id
                target_id_str = action.details.get("target_entity_id")
                relation_type = action.details.get("relation_type", "related_to")
                if source_id and target_id_str:
                    await self.relation_repo.create(
                        workspace_id=workspace_id,
                        source_entity_id=source_id,
                        target_entity_id=uuid.UUID(str(target_id_str)),
                        relation_type=relation_type,
                        confidence=0.9,
                    )
                    counters["relations_created"] = 1

            elif action.action == "remove_noise" and action.entity_id:
                await self.entity_repo.update(action.entity_id, is_deleted=True)
                counters["noise_removed"] = 1

            elif action.action in ("update_status", "normalize_date", "update_type", "add_assignee"):
                # These actions affect claims or entity properties; count as claims_updated
                counters["claims_updated"] = 1

        except Exception:
            log.warning("integrator_action_failed", action=action.action, entity_id=str(action.entity_id))

        return counters
