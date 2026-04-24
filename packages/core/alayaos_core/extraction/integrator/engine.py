"""IntegratorEngine — orchestrates dedup + enrichment pass over the knowledge graph.

Sprint 6: Multi-pass orchestrator with convergence detection.

Workflow per pass (up to max_passes=3):
  1. PanoramicPass — holistic triage: remove_noise, reclassify, rewrite,
                     create_from_cluster, link_cross_type.
  2. DeduplicatorV2 — batch-oriented entity deduplication.
  3. Flush after each pass (outer session.begin() handles commit).
  4. Converge if:
     a) total_actions == 0  → convergence_reason = "no_actions"
     b) action_hash unchanged from prior pass → "cycle_detected"
     c) pass_number == max_passes → "max_passes"
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import Any

import structlog

from alayaos_core.extraction.integrator.dedup import (
    DeduplicatorV2,
    EntityDeduplicator,
    assemble_batches,
    shortlist_candidates,
)
from alayaos_core.extraction.integrator.enricher import EntityEnricher
from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass
from alayaos_core.extraction.integrator.schemas import (
    DuplicatePair,
    EnrichmentAction,
    EntityWithContext,
    IntegratorRunResult,
)
from alayaos_core.extraction.writer import acquire_workspace_lock, release_workspace_lock

log = structlog.get_logger()

# Maximum number of panoramic→dedup passes before forcing convergence.
_MAX_PASSES = 3
_DEFAULT_PANORAMIC_MAX_ENTITIES = 500


class IntegratorEngine:
    """Orchestrates a full Integrator pass for a workspace.

    Workflow:
    1. Acquire workspace lock (prevents concurrent integrator runs)
    2. Atomically drain dirty-set via RENAME
    3. Load 48h window entities from DB
    4. Combine dirty + window entity sets
    5. Load entity context (claims, relations) for each entity
    6. Multi-pass loop (up to max_passes=3):
       a. PanoramicPass — structural triage
       b. DeduplicatorV2 — entity deduplication
       c. Commit
       d. Convergence check (no_actions | cycle_detected | max_passes)
    7. Batch enrich (single pass after convergence)
    8. Warm entity cache
    9. Return run result with counters, pass_count, convergence_reason
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
        self._panoramic_max_entities = self._coerce_positive_int(
            getattr(settings, "CONSOLIDATOR_PANORAMIC_MAX_ENTITIES", _DEFAULT_PANORAMIC_MAX_ENTITIES),
            default=_DEFAULT_PANORAMIC_MAX_ENTITIES,
        )

        # Embedding service injected in tests; created lazily in production
        self._embedding_service = None

    @staticmethod
    def _coerce_positive_int(value: Any, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int) and value > 0:
            return value
        return default

    async def run(
        self,
        workspace_id: uuid.UUID,
        session,
        *,
        run_id: uuid.UUID | None = None,
    ) -> IntegratorRunResult:
        """Execute Integrator pass with workspace-level lock.

        Args:
            workspace_id: Workspace to integrate.
            session:      Active DB session.
            run_id:       IntegratorRun ID for action provenance.  When None
                          a throwaway UUID is generated (backward-compat for
                          callers that create the run externally and use
                          update_counters separately).
        """
        lock_key = f"integrator:lock:{workspace_id}"
        token = await acquire_workspace_lock(self.redis, lock_key, timeout=600)
        if not token:
            return IntegratorRunResult(status="skipped", reason="locked")
        try:
            effective_run_id = run_id if run_id is not None else uuid.uuid4()
            return await self._run_locked(workspace_id, effective_run_id, session)
        finally:
            await release_workspace_lock(self.redis, lock_key, token)

    async def _run_locked(
        self,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        session,
    ) -> IntegratorRunResult:
        """Execute the integrator multi-pass loop (called while lock is held)."""
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

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
        entities_with_context = await self._load_entities_with_context(workspace_id, all_entity_ids)

        entities_scanned = len(entities_with_context)
        entities_deduplicated = 0
        noise_removed = 0
        relations_created = 0
        claims_updated = 0

        # Lazy-load entity types for panoramic pass (best-effort; panoramic
        # tolerates an empty list gracefully).
        entity_types: list = []

        # Build claims / relations index for panoramic prompt
        claims_by_entity: dict[uuid.UUID, list[dict]] = {e.id: e.claims for e in entities_with_context}
        relations_by_entity: dict[uuid.UUID, list[dict]] = {e.id: e.relations for e in entities_with_context}

        # Action repo for persisting audit records
        action_repo = IntegratorActionRepository(session)

        # Multi-pass convergence loop
        pass_number = 1
        convergence_reason = "max_passes"  # default if loop completes without break
        previous_hash: int | None = None

        for pass_number in range(1, _MAX_PASSES + 1):
            # Re-fetch entities on pass 2+ to avoid stale data after mutations.
            # Re-query the window so newly created entities (e.g. from create_from_cluster)
            # are picked up, and deleted entities are excluded.
            if pass_number > 1:
                fresh_window = await self.entity_repo.list_recent(workspace_id, hours=window_hours)
                all_entity_ids = dirty_entity_ids | {e.id for e in fresh_window}
                entities_with_context = await self._load_entities_with_context(workspace_id, all_entity_ids)
                claims_by_entity = {e.id: e.claims for e in entities_with_context}
                relations_by_entity = {e.id: e.relations for e in entities_with_context}

            log.info(
                "integrator_pass_start",
                workspace_id=str(workspace_id),
                pass_number=pass_number,
            )

            # ── Panoramic pass ──
            panoramic_pass = PanoramicPass(
                llm_service=self.llm,
                session=session,
                max_entities=self._panoramic_max_entities,
            )
            panoramic_result = await panoramic_pass.run(
                workspace_id=workspace_id,
                entities=entities_with_context,
                entity_types=entity_types,
                claims_by_entity=claims_by_entity,
                relations_by_entity=relations_by_entity,
            )

            applied_p = await self._apply_panoramic_actions(
                panoramic_result.actions,
                workspace_id,
                run_id,
                pass_number=pass_number,
                session=session,
                action_repo=action_repo,
            )
            # Count only the remove_noise actions (not reclassify/rewrite/etc.)
            noise_removed += sum(1 for a in panoramic_result.actions if a.action == "remove_noise")

            # ── Dedup v2 pass ──
            applied_d = 0
            dedup_signatures: list[str] = []
            if entities_with_context:
                applied_d, dedup_signatures = await self._dedup_v2(
                    entities_with_context,
                    workspace_id,
                    session,
                    run_id=run_id,
                    action_repo=action_repo,
                )
                entities_deduplicated += applied_d

            # Flush after each pass; the outer session.begin() context manager handles commit.
            # (Calling session.commit() here would close the managed transaction in workers.)
            await session.flush()

            total_actions = applied_p + applied_d
            log.info(
                "integrator_pass_done",
                workspace_id=str(workspace_id),
                pass_number=pass_number,
                applied_p=applied_p,
                applied_d=applied_d,
                total_actions=total_actions,
            )

            # Convergence check 1: no actions this pass
            if total_actions == 0:
                convergence_reason = "no_actions"
                break

            # Convergence check 2: cycle detection via action signature hash.
            # Include panoramic actions and dedup entity IDs (not just count) so that
            # passes with the same count but different entity merges do not collide.
            action_hash = hash(frozenset([str(a) for a in panoramic_result.actions] + dedup_signatures))
            if previous_hash is not None and action_hash == previous_hash:
                convergence_reason = "cycle_detected"
                break
            previous_hash = action_hash
        else:
            # for-loop completed without break → max_passes
            convergence_reason = "max_passes"

        # ── Reload entities after convergence, before enrichment ──
        # Ensures enrichment sees post-consolidation state: deleted entities excluded,
        # newly created entities (e.g. from create_from_cluster) included.
        fresh_window = await self.entity_repo.list_recent(workspace_id, hours=window_hours)
        all_entity_ids = dirty_entity_ids | {e.id for e in fresh_window}
        entities_with_context = await self._load_entities_with_context(workspace_id, all_entity_ids)

        # ── Enrichment (single pass after convergence) ──
        enrichment_result = await self._enricher.enrich_batch(entities_with_context)
        entities_enriched = len(entities_with_context)

        for action in enrichment_result.actions:
            counters = await self._apply_action(action, workspace_id, session)
            relations_created += counters.get("relations_created", 0)
            claims_updated += counters.get("claims_updated", 0)

        # ── Warm entity cache with processed entities ──
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
            pass_count=pass_number,
            convergence_reason=convergence_reason,
        )

    # ---------------------------------------------------------------------------
    # Panoramic action application
    # ---------------------------------------------------------------------------

    async def _apply_panoramic_actions(
        self,
        actions,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        pass_number: int,
        session,
        action_repo,
    ) -> int:
        """Apply each PanoramicAction and persist an IntegratorAction audit record.

        Supported action types:
          remove_noise        → soft-delete entity
          reclassify          → update entity_type_id
          rewrite             → update name + description
          create_from_cluster → create parent entity + part_of relations
          link_cross_type     → create relation between two existing entities

        Returns the count of successfully applied actions.
        """

        applied = 0
        for action in actions:
            try:
                await self._apply_single_panoramic_action(
                    action,
                    workspace_id,
                    run_id,
                    pass_number=pass_number,
                    session=session,
                    action_repo=action_repo,
                )
                applied += 1
            except Exception:
                log.warning(
                    "integrator_panoramic_action_failed",
                    action=action.action,
                    entity_id=str(action.entity_id) if action.entity_id else None,
                )
        return applied

    async def _apply_single_panoramic_action(
        self,
        action,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        pass_number: int,
        session,
        action_repo,
    ) -> None:
        """Apply one PanoramicAction and record it in integrator_actions."""
        from alayaos_core.schemas.integrator_action import IntegratorActionCreate

        entity_id = action.entity_id
        params = dict(action.params)
        inverse: dict = {}
        targets: list = []

        if action.action == "remove_noise":
            # Soft-delete the entity
            if entity_id is not None:
                entity = await self.entity_repo.get_by_id(entity_id)
                if entity is not None:
                    inverse = {"name": entity.name, "is_deleted": False}
                await self.entity_repo.update(entity_id, is_deleted=True)

        elif action.action == "reclassify":
            # Update entity_type to to_type
            if entity_id is not None:
                entity = await self.entity_repo.get_by_id(entity_id)
                if entity is not None:
                    from alayaos_core.repositories.entity_type import EntityTypeRepository

                    et_repo = EntityTypeRepository(session, workspace_id)
                    to_type_slug = params.get("to_type")
                    if to_type_slug:
                        entity_type = await et_repo.get_by_slug(workspace_id, to_type_slug)
                        if entity_type:
                            inverse = {
                                "old_type_id": str(entity.entity_type_id),
                                "old_type": params.get("from_type"),
                            }
                            params["new_type_id"] = str(entity_type.id)
                            entity.entity_type_id = entity_type.id
                            await session.flush()

        elif action.action == "rewrite":
            # Update name and description
            if entity_id is not None:
                entity = await self.entity_repo.get_by_id(entity_id)
                if entity is not None:
                    inverse = {
                        "name": entity.name,
                        "description": getattr(entity, "description", "") or "",
                    }
                    new_name = params.get("new_name")
                    new_desc = params.get("new_description")
                    update_kwargs: dict = {}
                    if new_name:
                        update_kwargs["name"] = new_name
                    if new_desc:
                        update_kwargs["description"] = new_desc
                    if update_kwargs:
                        await self.entity_repo.update(entity_id, **update_kwargs)

        elif action.action == "create_from_cluster":
            # Create a parent entity and link children via part_of relations
            child_ids_raw: list = params.get("child_ids", [])
            new_entity_name = params.get("name", "")
            new_entity_desc = params.get("description", "")
            new_entity_type_slug = params.get("entity_type", "")
            if new_entity_name and new_entity_type_slug:
                from alayaos_core.repositories.entity_type import EntityTypeRepository

                et_repo = EntityTypeRepository(session, workspace_id)
                entity_type = await et_repo.get_by_slug(workspace_id, new_entity_type_slug)
                if entity_type:
                    new_entity = await self.entity_repo.create(
                        workspace_id=workspace_id,
                        name=new_entity_name,
                        entity_type_id=entity_type.id,
                        description=new_entity_desc,
                    )
                    entity_id = new_entity.id
                    params["created_entity_id"] = str(entity_id)
                    # Create part_of relations from each child to the new parent
                    for cid_raw in child_ids_raw:
                        try:
                            cid = uuid.UUID(str(cid_raw))
                        except (ValueError, AttributeError):
                            continue
                        with contextlib.suppress(Exception):
                            rel = await self.relation_repo.create(
                                workspace_id=workspace_id,
                                source_entity_id=cid,
                                target_entity_id=entity_id,
                                relation_type="part_of",
                                confidence=action.confidence,
                            )
                            targets.append(str(rel.id))

        elif action.action == "link_cross_type":
            # Create a relation between two existing entities
            source_id_raw = params.get("source_id")
            target_id_raw = params.get("target_id")
            relation_type = params.get("relation_type", "related_to")
            if source_id_raw and target_id_raw:
                try:
                    source_id = uuid.UUID(str(source_id_raw))
                    target_id = uuid.UUID(str(target_id_raw))
                except (ValueError, AttributeError):
                    source_id = None
                    target_id = None
                if source_id and target_id:
                    with contextlib.suppress(Exception):
                        rel = await self.relation_repo.create(
                            workspace_id=workspace_id,
                            source_entity_id=source_id,
                            target_entity_id=target_id,
                            relation_type=relation_type,
                            confidence=action.confidence,
                        )
                        targets.append(str(rel.id))
                        params["relation_id"] = str(rel.id)

        # Persist audit record (best-effort — failure doesn't abort the action)
        if action_repo is not None:
            with contextlib.suppress(Exception):
                await action_repo.create(
                    workspace_id=workspace_id,
                    data=IntegratorActionCreate(
                        run_id=run_id,
                        pass_number=pass_number,
                        action_type=action.action,
                        entity_id=entity_id,
                        params=params,
                        targets=targets,
                        inverse=inverse,
                        confidence=action.confidence,
                        rationale=action.rationale,
                    ),
                )

    # ---------------------------------------------------------------------------
    # Entity loading helper
    # ---------------------------------------------------------------------------

    async def _load_entities_with_context(
        self,
        workspace_id: uuid.UUID,
        entity_ids: set[uuid.UUID],
    ) -> list[EntityWithContext]:
        """Load entities with claims and relations for the given entity ID set.

        Used both for the initial load and for refreshing between passes so that
        mutations from the previous pass are visible to the next one.
        """
        entities_with_context: list[EntityWithContext] = []
        for entity_id in entity_ids:
            entity = await self.entity_repo.get_by_id(entity_id)
            if entity is None or getattr(entity, "is_deleted", False):
                continue

            claims, _, _ = await self.claim_repo.list(entity_id=entity_id, limit=50)
            claims_dicts = [{"predicate": c.predicate, "value": c.value, "status": c.status} for c in claims]

            relations, _, _ = await self.relation_repo.list(entity_id=entity_id, limit=50)
            relations_dicts = [
                {
                    "source": str(r.source_entity_id),
                    "target": str(r.target_entity_id),
                    "type": r.relation_type,
                }
                for r in relations
            ]

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
        return entities_with_context

    # ---------------------------------------------------------------------------
    # Embedding service
    # ---------------------------------------------------------------------------

    def _get_embedding_service(self):
        """Return the embedding service, creating a FastEmbedService lazily if not injected."""
        if self._embedding_service is None:
            from alayaos_core.services.embedding import FastEmbedService

            model = getattr(self.settings, "EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
            dimensions = getattr(self.settings, "EMBEDDING_DIMENSIONS", 1024)
            self._embedding_service = FastEmbedService(model_name=model, dimensions=dimensions)
        return self._embedding_service

    # ---------------------------------------------------------------------------
    # Dedup v2
    # ---------------------------------------------------------------------------

    async def _dedup_v2(
        self,
        entities: list[EntityWithContext],
        workspace_id: uuid.UUID,
        session,
        *,
        run_id: uuid.UUID | None = None,
        action_repo=None,
    ) -> tuple[int, list[str]]:
        """Dedup v2: batch-oriented deduplication with composite signal ordering.

        1. Filter out entities with entity_type == 'unknown' (no type = unpaireable).
        2. Embed entity names (for cosine signal in composite score).
        3. Use assemble_batches to group by type and chunk into N=batch_size.
        4. DeduplicatorV2.execute_batches: LLM batch call → MergeGroups → apply merges.

        Falls back to _shortlist_dedup if embedding fails.
        Returns (total_merged, merge_signatures) where merge_signatures are used for
        cycle detection hashing — each entry is "merge:<winner_id>:[<loser_ids>]".

        Args:
            run_id:      IntegratorRun ID for action provenance.  Falls back to
                         uuid.UUID(int=0) only when None — callers should always
                         supply the real run_id.
            action_repo: IntegratorActionRepository for audit records.
        """
        effective_run_id = run_id if run_id is not None else uuid.UUID(int=0)

        if len(entities) < 2:
            return 0, []

        # Skip entities without a resolved type — grouping unknowns together would pair
        # unrelated entities and produces noise.
        resolved = [e for e in entities if e.entity_type != "unknown"]
        skipped = len(entities) - len(resolved)
        if skipped:
            log.debug("integrator_dedup_v2_skip_typeless", skipped=skipped)
        entities = resolved
        if len(entities) < 2:
            return 0, []

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
            merged = await self._merge_duplicates(
                dup_pairs, workspace_id, session, run_id=effective_run_id, action_repo=action_repo
            )
            sigs = [f"merge:{p.entity_a_id}:{sorted([str(p.entity_b_id)])}" for p in dup_pairs]
            return merged, sigs

        if len(vectors) != len(entities):
            log.warning(
                "integrator_dedup_v2_embed_length_mismatch",
                entity_count=len(entities),
                vector_count=len(vectors),
                msg="falling back to shortlist dedup",
            )
            dup_pairs = await self._shortlist_dedup(entities)
            merged = await self._merge_duplicates(
                dup_pairs, workspace_id, session, run_id=effective_run_id, action_repo=action_repo
            )
            sigs = [f"merge:{p.entity_a_id}:{sorted([str(p.entity_b_id)])}" for p in dup_pairs]
            return merged, sigs

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
        all_signatures: list[str] = []
        for entity_type, type_batches in batches_by_type.items():
            merged, sigs = await self._deduplicator_v2.execute_batches(
                batches=type_batches,
                entity_type=entity_type,
                workspace_id=workspace_id,
                run_id=effective_run_id,
                entity_repo=self.entity_repo,
                session=session,
                action_repo=action_repo,
            )
            total_merged += merged
            all_signatures.extend(sigs)

        return total_merged, all_signatures

    # ---------------------------------------------------------------------------
    # Shortlist dedup (fallback when embedding fails)
    # ---------------------------------------------------------------------------

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

    async def _merge_duplicates(
        self,
        pairs,
        workspace_id: uuid.UUID,
        session,
        *,
        run_id: uuid.UUID | None = None,
        action_repo=None,
    ) -> int:
        """Merge duplicate entity pairs: keep entity_a, soft-delete entity_b, merge aliases.

        Also reassigns claims, relations, and vector_chunks from entity_b to entity_a
        before soft-deleting entity_b, so no data is orphaned.

        Args:
            run_id:      IntegratorRun ID for audit records.  Optional for backward compat.
            action_repo: IntegratorActionRepository for writing audit records.  When None,
                         no audit records are written (v1 fallback path backward compat).

        Returns the number of pairs successfully merged.
        """
        merged = 0
        for pair in pairs:
            entity_b = await self.entity_repo.get_by_id(pair.entity_b_id)
            entity_a = await self.entity_repo.get_by_id(pair.entity_a_id)
            if not entity_a or not entity_b:
                continue
            # Fallback pairwise dedup must share the same merge/audit path as DeduplicatorV2
            # so rollback metadata stays complete even when embeddings fail.
            effective_action_repo = action_repo if run_id is not None else None
            merged += await self._deduplicator_v2._apply_merge_group(
                winner_id=entity_a.id,
                loser_ids=[entity_b.id],
                merged_name=entity_a.name,
                merged_description=getattr(entity_a, "description", "") or "",
                merged_aliases=list(dict.fromkeys([*(entity_a.aliases or []), *(entity_b.aliases or [])])),
                confidence=pair.score,
                rationale=f"fallback merge via {pair.method}",
                workspace_id=workspace_id,
                run_id=run_id or uuid.UUID(int=0),
                entity_repo=self.entity_repo,
                session=session,
                action_repo=effective_action_repo,
            )
        return merged

    # ---------------------------------------------------------------------------
    # Enrichment action application (unchanged from previous sprint)
    # ---------------------------------------------------------------------------

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
