"""IntegratorEngine — orchestrates dedup + enrichment pass over the knowledge graph."""

from __future__ import annotations

import contextlib
import time
import uuid

import structlog
from sqlalchemy import text

from alayaos_core.extraction.integrator.dedup import (
    DeduplicatorV2,
    EntityDeduplicator,
    assemble_batches,
    shortlist_candidates,
)
from alayaos_core.extraction.integrator.enricher import EntityEnricher
from alayaos_core.extraction.integrator.schemas import (
    DuplicatePair,
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

        # Shortlist config (Sprint S6: vector-similarity pre-filter before LLM verify)
        self._shortlist_k: int = getattr(settings, "INTEGRATOR_DEDUP_SHORTLIST_K", 5)
        self._shortlist_threshold: float = getattr(settings, "INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD", 0.85)

        # Dedup v2 (Sprint 5): batch-oriented deduplicator with composite signal ordering
        self._dedup_batch_size: int = getattr(settings, "INTEGRATOR_DEDUP_BATCH_SIZE", 9)
        self._deduplicator_v2 = DeduplicatorV2(llm=llm, batch_size=self._dedup_batch_size)

        # Embedding service injected in tests; created lazily in production
        self._embedding_service = None

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

        created_at_key = f"dirty_set:{workspace_id}:created_at"
        try:
            await self.redis.rename(dirty_key, processing_key)
            raw_members = await self.redis.smembers(processing_key)
            await self.redis.delete(processing_key)
            # Clear the age marker so next batch starts fresh
            await self.redis.delete(created_at_key)
            for member in raw_members:
                member_str = member.decode() if isinstance(member, bytes) else member
                with contextlib.suppress(ValueError):
                    dirty_entity_ids.add(uuid.UUID(member_str))
        except Exception as exc:
            # ResponseError("no such key") means dirty-set doesn't exist — that's fine
            exc_str = str(exc).lower()
            if "no such key" not in exc_str and "notfound" not in exc_str:
                # Unexpected error after RENAME — re-raise to prevent data loss
                log.error("integrator_dirty_set_error", workspace_id=str(workspace_id), error=str(exc))
                raise

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

        # Step 5: Deduplicate via dedup v2 (batch-oriented, no threshold gate)
        if entities_with_context:
            entities_deduplicated = await self._dedup_v2(entities_with_context, workspace_id, session)
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

    def _get_embedding_service(self):
        """Return the embedding service, creating a FastEmbedService lazily if not injected."""
        if self._embedding_service is None:
            from alayaos_core.services.embedding import FastEmbedService

            model = getattr(self.settings, "EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
            dimensions = getattr(self.settings, "EMBEDDING_DIMENSIONS", 1024)
            self._embedding_service = FastEmbedService(model_name=model, dimensions=dimensions)
        return self._embedding_service

    async def _dedup_v2(
        self,
        entities: list[EntityWithContext],
        workspace_id: uuid.UUID,
        session,
    ) -> int:
        """Dedup v2: batch-oriented deduplication with composite signal ordering.

        1. Filter out entities with entity_type == 'unknown' (no type = unpaireable).
        2. Embed entity names (for cosine signal in composite score).
        3. Use assemble_batches to group by type and chunk into N=batch_size.
        4. DeduplicatorV2.execute_batches: LLM batch call → MergeGroups → apply merges.

        Falls back to _shortlist_dedup if embedding fails.
        Returns the number of entity merges performed.
        """
        if len(entities) < 2:
            return 0

        # Skip entities without a resolved type — grouping unknowns together would pair
        # unrelated entities and produces noise.
        resolved = [e for e in entities if e.entity_type != "unknown"]
        skipped = len(entities) - len(resolved)
        if skipped:
            log.debug("integrator_dedup_v2_skip_typeless", skipped=skipped)
        entities = resolved
        if len(entities) < 2:
            return 0

        # Embed entity names for cosine component of composite signal
        embed_svc = self._get_embedding_service()
        names = [e.name for e in entities]
        try:
            vectors = await embed_svc.embed_texts(names)
        except Exception:
            log.warning(
                "integrator_dedup_v2_embed_failed",
                entity_count=len(entities),
                msg="falling back to shortlist dedup",
            )
            dup_pairs = await self._shortlist_dedup(entities)
            return await self._merge_duplicates(dup_pairs, workspace_id, session)

        if len(vectors) != len(entities):
            log.warning(
                "integrator_dedup_v2_embed_length_mismatch",
                entity_count=len(entities),
                vector_count=len(vectors),
                msg="falling back to shortlist dedup",
            )
            dup_pairs = await self._shortlist_dedup(entities)
            return await self._merge_duplicates(dup_pairs, workspace_id, session)

        embeddings: dict[uuid.UUID, list[float]] = {e.id: v for e, v in zip(entities, vectors, strict=True)}

        # Assemble batches grouped by entity type, ordered by composite signal
        batches_by_type: dict[str, list[list[EntityWithContext]]] = {}
        all_batches = assemble_batches(entities, embeddings, batch_size=self._dedup_batch_size)

        # Group batches by entity_type for per-type LLM calls
        for batch in all_batches:
            if not batch:
                continue
            etype = batch[0].entity_type
            batches_by_type.setdefault(etype, []).append(batch)

        log.info(
            "integrator_dedup_v2_batches",
            workspace_id=str(workspace_id),
            entity_count=len(entities),
            total_batches=len(all_batches),
        )

        total_merged = 0
        for entity_type, type_batches in batches_by_type.items():
            # We don't have a run_id at this level — use a deterministic placeholder.
            # The action_repo is not wired into the engine yet; pass None for now.
            merged = await self._deduplicator_v2.execute_batches(
                batches=type_batches,
                entity_type=entity_type,
                workspace_id=workspace_id,
                run_id=uuid.UUID(int=0),  # placeholder — no run_id in engine scope
                entity_repo=self.entity_repo,
                session=session,
                action_repo=None,
            )
            total_merged += merged

        return total_merged

    async def _shortlist_dedup(self, entities: list[EntityWithContext]) -> list[DuplicatePair]:
        """Vector shortlist → LLM-verify dedup (replaces O(n²) rapidfuzz loop).

        1. Embed all entity names via embedding service (fast, CPU-only, no DB).
        2. Use shortlist_candidates to find top-K similar pairs per entity type.
        3. LLM-verify only the shortlisted pairs.

        This reduces LLM calls from O(n²) to at most n * K.
        """
        if len(entities) < 2:
            return []

        # Skip entities with unresolvable entity_type — "same-type only" guarantee requires a
        # real type slug. Grouping unknowns together would pair unrelated entities.
        resolved = [e for e in entities if e.entity_type != "unknown"]
        skipped = len(entities) - len(resolved)
        if skipped:
            log.debug("integrator_shortlist_skip_typeless", skipped=skipped)
        entities = resolved

        if len(entities) < 2:
            return []

        # 1. Embed entity names
        embed_svc = self._get_embedding_service()
        names = [e.name for e in entities]
        try:
            vectors = await embed_svc.embed_texts(names)
        except Exception:
            log.warning(
                "integrator_shortlist_embed_failed",
                entity_count=len(entities),
                msg="falling back to rapidfuzz dedup",
            )
            # Graceful fallback to the existing rapidfuzz-based deduplicator
            return await self._deduplicator.find_duplicates(entities)

        if len(vectors) != len(entities):
            log.warning(
                "integrator_shortlist_embed_length_mismatch",
                entity_count=len(entities),
                vector_count=len(vectors),
                msg="falling back to rapidfuzz dedup",
            )
            return await self._deduplicator.find_duplicates(entities)
        embeddings: dict[uuid.UUID, list[float]] = {e.id: v for e, v in zip(entities, vectors, strict=True)}

        # 2. Build shortlist of candidate pairs via cosine similarity
        candidate_pairs = shortlist_candidates(
            entities,
            embeddings,
            k=self._shortlist_k,
            threshold=self._shortlist_threshold,
        )

        log.info(
            "integrator_shortlist_built",
            entity_count=len(entities),
            candidate_pairs=len(candidate_pairs),
            k=self._shortlist_k,
            threshold=self._shortlist_threshold,
        )

        # 3. LLM-verify each shortlisted pair
        dup_pairs: list[DuplicatePair] = []
        for entity_a, entity_b in candidate_pairs:
            is_same = await self._deduplicator.llm_check_pair(entity_a, entity_b)
            if is_same:
                dup_pairs.append(
                    DuplicatePair(
                        entity_a_id=entity_a.id,
                        entity_b_id=entity_b.id,
                        entity_a_name=entity_a.name,
                        entity_b_name=entity_b.name,
                        score=self._shortlist_threshold,
                        method="vector_shortlist",
                    )
                )
        return dup_pairs

    async def _merge_duplicates(self, pairs, workspace_id: uuid.UUID, session) -> int:
        """Merge duplicate entity pairs: keep entity_a, soft-delete entity_b, merge aliases.

        Also reassigns claims, relations, and vector_chunks from entity_b to entity_a
        before soft-deleting entity_b, so no data is orphaned.

        Returns the number of pairs successfully merged.
        """
        merged = 0
        for pair in pairs:
            entity_b = await self.entity_repo.get_by_id(pair.entity_b_id)
            entity_a = await self.entity_repo.get_by_id(pair.entity_a_id)
            if not entity_a or not entity_b:
                continue
            # Step 1: Merge aliases — union of both alias lists + entity_b's name as an alias
            new_aliases = list(set(list(entity_a.aliases or []) + list(entity_b.aliases or []) + [entity_b.name]))
            await self.entity_repo.update(entity_a.id, aliases=new_aliases)
            # Step 2: Reassign claims from entity_b to entity_a
            await session.execute(
                text("UPDATE l2_claims SET entity_id = :a_id WHERE entity_id = :b_id AND workspace_id = :ws_id"),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Step 3: Reassign relations where entity_b is the source (skip would-be self-refs)
            await session.execute(
                text(
                    "UPDATE l1_relations SET source_entity_id = :a_id"
                    " WHERE source_entity_id = :b_id AND target_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Delete b→a relations that would become self-referential
            await session.execute(
                text(
                    "DELETE FROM l1_relations"
                    " WHERE source_entity_id = :b_id AND target_entity_id = :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Step 4: Reassign relations where entity_b is the target (skip would-be self-refs)
            await session.execute(
                text(
                    "UPDATE l1_relations SET target_entity_id = :a_id"
                    " WHERE target_entity_id = :b_id AND source_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Delete a→b relations that would become self-referential
            await session.execute(
                text(
                    "DELETE FROM l1_relations"
                    " WHERE source_entity_id = :a_id AND target_entity_id = :b_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Step 5: Deduplicate relations on entity_a (same source, target, relation_type)
            await session.execute(
                text(
                    "DELETE FROM l1_relations WHERE id IN ("
                    "  SELECT id FROM ("
                    "    SELECT id, ROW_NUMBER() OVER ("
                    "      PARTITION BY workspace_id, source_entity_id, target_entity_id, relation_type"
                    "      ORDER BY created_at"
                    "    ) AS rn FROM l1_relations"
                    "    WHERE (source_entity_id = :a_id OR target_entity_id = :a_id)"
                    "    AND workspace_id = :ws_id"
                    "  ) ranked WHERE rn > 1"
                    ")"
                ),
                {"a_id": entity_a.id, "ws_id": workspace_id},
            )
            # Step 6: Reassign entity vector_chunks from entity_b to entity_a
            await session.execute(
                text(
                    "UPDATE vector_chunks SET source_id = :a_id"
                    " WHERE source_id = :b_id AND source_type = 'entity' AND workspace_id = :ws_id"
                ),
                {"a_id": entity_a.id, "b_id": entity_b.id, "ws_id": workspace_id},
            )
            # Step 7: Record provenance and soft-delete entity_b
            props = dict(entity_b.properties or {})
            props["merged_into"] = str(entity_a.id)
            await self.entity_repo.update(entity_b.id, is_deleted=True, properties=props)
            merged += 1
        return merged

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

            elif action.action == "update_type" and action.entity_id:
                new_type_slug = action.details.get("entity_type")
                if new_type_slug:
                    # Resolve slug to entity_type_id and update the entity's type directly
                    from alayaos_core.repositories.entity_type import EntityTypeRepository

                    et_repo = EntityTypeRepository(session, workspace_id)
                    entity_type = await et_repo.get_by_slug(workspace_id, new_type_slug)
                    if entity_type:
                        entity = await self.entity_repo.get_by_id(action.entity_id)
                        if entity:
                            entity.entity_type_id = entity_type.id
                            await session.flush()
                    counters["claims_updated"] = 1

            elif action.action in ("update_status", "add_assignee") and action.entity_id:
                # Merge action details into existing entity properties (not wholesale replace)
                entity = await self.entity_repo.get_by_id(action.entity_id)
                if entity:
                    merged_props = dict(entity.properties or {})
                    merged_props.update(action.details)
                    await self.entity_repo.update(action.entity_id, properties=merged_props)
                counters["claims_updated"] = 1

            elif action.action == "normalize_date" and action.entity_id:
                from alayaos_core.extraction.integrator.date_normalizer import DateNormalizer

                normalizer = DateNormalizer()
                entity = await self.entity_repo.get_by_id(action.entity_id)
                if entity:
                    merged_props = dict(entity.properties or {})
                    raw_date = action.details.get("date_value", "")
                    normalized = normalizer.normalize(raw_date)
                    if normalized:
                        merged_props["normalized_date"] = normalized
                    # Merge remaining action details regardless of normalization outcome
                    merged_props.update(action.details)
                    await self.entity_repo.update(action.entity_id, properties=merged_props)
                counters["claims_updated"] = 1

        except Exception:
            log.warning("integrator_action_failed", action=action.action, entity_id=str(action.entity_id))

        return counters
