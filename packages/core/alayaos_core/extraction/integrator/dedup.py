"""EntityDeduplicator — 3-tier entity deduplication using rapidfuzz + transliteration + LLM.

Sprint S6 adds a vector-shortlist pass: instead of comparing every O(n²) pair with the LLM,
we first embed entity names in Python (fast, no DB), group by entity_type, and retain only the
top-K nearest neighbours per entity above a cosine-similarity threshold.  Only those pairs go
to the (slow) LLM verifier.

Sprint 5 (dedup v2) introduces DeduplicatorV2:
- Drops the similarity threshold gate entirely.
- Uses a composite signal (cosine + trigram + co-event + shared-owner) only for ordering.
- Groups entities by type, assembles batches of N=9, and sends each batch to a focused LLM prompt.
- LLM returns DedupResult with MergeGroup objects describing winner/loser relationships.
- Merge execution: winner gets merged_name/description/union-aliases; losers soft-deleted.
"""

from __future__ import annotations

import math
import uuid

import structlog

from alayaos_core.extraction.integrator.schemas import DuplicatePair, EntityMatchResult, EntityWithContext
from alayaos_core.extraction.resolver import transliterate_name

log = structlog.get_logger()

# Minimum name length for fuzzy matching (short names are too unreliable)
_MIN_NAME_LENGTH = 4


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (assumed pre-normalised or normalised here).

    Returns 0.0 on dimension mismatch or NaN result rather than raising or silently truncating.
    """
    if len(a) != len(b):
        log.warning("cosine_similarity_dimension_mismatch", len_a=len(a), len_b=len(b))
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    result = dot / (norm_a * norm_b)
    if math.isnan(result):
        return 0.0
    return result


def shortlist_candidates(
    entities: list[EntityWithContext],
    embeddings: dict[uuid.UUID, list[float]],
    *,
    k: int = 5,
    threshold: float = 0.85,
) -> list[tuple[EntityWithContext, EntityWithContext]]:
    """Build a shortlist of candidate duplicate pairs via vector similarity.

    Groups entities by entity_type (slug), then for each entity finds the top-K
    nearest neighbours with cosine similarity >= threshold within the same type.
    Returns deduplicated pairs (A, B) where A.id < B.id (string ordering of UUIDs).

    This is a pure Python operation — no DB access, no LLM calls.

    Args:
        entities:   Entities to compare.
        embeddings: Pre-computed embedding for each entity id.
        k:          Maximum candidates per entity.
        threshold:  Minimum cosine similarity to include a pair.

    Returns:
        List of (entity_a, entity_b) pairs, deduplicated.
    """
    if len(entities) < 2:
        return []

    # Filter out entities with names too short to be reliable (same guard as EntityDeduplicator)
    entities = [e for e in entities if len(e.name) >= _MIN_NAME_LENGTH]
    if len(entities) < 2:
        return []

    # Group by entity_type (slug acts as the discriminator; entity_type_id stored in properties
    # as string if available, but we use slug here to match EntityWithContext schema).
    by_type: dict[str, list[EntityWithContext]] = {}
    for entity in entities:
        by_type.setdefault(entity.entity_type, []).append(entity)

    seen: set[frozenset[uuid.UUID]] = set()
    pairs: list[tuple[EntityWithContext, EntityWithContext]] = []

    for group in by_type.values():
        if len(group) < 2:
            continue

        for entity in group:
            emb_a = embeddings.get(entity.id)
            if emb_a is None:
                continue

            # Compute cosine similarity against all other members of this type
            scored: list[tuple[float, EntityWithContext]] = []
            for candidate in group:
                if candidate.id == entity.id:
                    continue
                emb_b = embeddings.get(candidate.id)
                if emb_b is None:
                    continue
                sim = _cosine_similarity(emb_a, emb_b)
                if sim >= threshold:
                    scored.append((sim, candidate))

            # Keep only the top-K by similarity
            scored.sort(key=lambda t: t[0], reverse=True)
            for _, candidate in scored[:k]:
                pair_key: frozenset[uuid.UUID] = frozenset([entity.id, candidate.id])
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                # Canonical order: smaller UUID string first
                if str(entity.id) < str(candidate.id):
                    pairs.append((entity, candidate))
                else:
                    pairs.append((candidate, entity))

    return pairs


class EntityDeduplicator:
    """Find duplicate entity pairs using 3-tier matching.

    Tier 1: rapidfuzz batch scoring (score >= threshold → fuzzy match)
    Tier 2: transliteration re-score for Cyrillic↔Latin names
    Tier 3: LLM disambiguation for ambiguous band
    """

    def __init__(self, llm, threshold: float = 0.85, ambiguous_low: float = 0.70) -> None:
        self.llm = llm
        self.threshold = threshold
        self.ambiguous_low = ambiguous_low

    async def find_duplicates(self, entities: list[EntityWithContext]) -> list[DuplicatePair]:
        """Find duplicate entity pairs using 3-tier matching."""
        if len(entities) < 2:
            return []

        # Filter entities with names too short to be reliable
        scoreable = [e for e in entities if len(e.name) >= _MIN_NAME_LENGTH]
        if len(scoreable) < 2:
            return []

        from rapidfuzz import fuzz, process
        from rapidfuzz.distance import JaroWinkler

        # Group by entity_type so we never compare entities of different types
        # (mirrors the same guard in shortlist_candidates to prevent cross-type merges).
        by_type: dict[str, list[EntityWithContext]] = {}
        for entity in scoreable:
            by_type.setdefault(entity.entity_type, []).append(entity)

        pairs: list[DuplicatePair] = []
        seen: set[frozenset] = set()

        for group in by_type.values():
            if len(group) < 2:
                continue

            # Use index-based lookup to handle same-name entities correctly
            names = [e.name for e in group]

            for entity in group:
                # Batch extract top matches for this entity's name
                matches = process.extract(
                    entity.name,
                    names,
                    scorer=fuzz.WRatio,
                    limit=len(names),
                )

                # Precompute transliterated form for this entity
                translit_entity = transliterate_name(entity.name)

                for _candidate_name, score_raw, idx in matches:
                    candidate = group[idx]

                    # Skip self
                    if candidate.id == entity.id:
                        continue

                    # Dedup pair ordering (avoid A→B and B→A)
                    pair_key = frozenset([entity.id, candidate.id])
                    if pair_key in seen:
                        continue

                    # WRatio returns 0-100, normalize to 0.0-1.0
                    score = score_raw / 100.0

                    # Tier 2: transliteration re-score (always compute for cross-script matching)
                    translit_candidate = transliterate_name(candidate.name)
                    translit_score = max(
                        JaroWinkler.normalized_similarity(translit_entity, candidate.name.lower()),
                        JaroWinkler.normalized_similarity(entity.name.lower(), translit_candidate),
                        JaroWinkler.normalized_similarity(translit_entity, translit_candidate),
                    )

                    best_score = max(score, translit_score)

                    if score >= self.threshold:
                        seen.add(pair_key)
                        pairs.append(
                            DuplicatePair(
                                entity_a_id=entity.id,
                                entity_b_id=candidate.id,
                                entity_a_name=entity.name,
                                entity_b_name=candidate.name,
                                score=score,
                                method="fuzzy",
                            )
                        )
                    elif translit_score >= self.threshold:
                        # Transliteration gives a high score (cross-script match)
                        seen.add(pair_key)
                        pairs.append(
                            DuplicatePair(
                                entity_a_id=entity.id,
                                entity_b_id=candidate.id,
                                entity_a_name=entity.name,
                                entity_b_name=candidate.name,
                                score=translit_score,
                                method="transliteration",
                            )
                        )
                    elif best_score >= self.ambiguous_low:
                        # Tier 3: LLM fallback for ambiguous band
                        seen.add(pair_key)  # mark as seen regardless of LLM result
                        is_same = await self._llm_check(entity, candidate)
                        if is_same:
                            pairs.append(
                                DuplicatePair(
                                    entity_a_id=entity.id,
                                    entity_b_id=candidate.id,
                                    entity_a_name=entity.name,
                                    entity_b_name=candidate.name,
                                    score=best_score,
                                    method="llm",
                                )
                            )

        return pairs

    async def llm_check_pair(self, entity_a: EntityWithContext, entity_b: EntityWithContext) -> bool:
        """Public API: ask LLM whether two entities represent the same real-world entity.

        Used by IntegratorEngine._shortlist_dedup to verify shortlisted pairs.
        """
        return await self._llm_check(entity_a, entity_b)

    async def _llm_check(self, entity_a: EntityWithContext, entity_b: EntityWithContext) -> bool:
        """Ask LLM whether two entities represent the same real-world entity."""
        prompt = (
            "Are these the same entity?\n"
            f'Entity A: name="{entity_a.name}", type="{entity_a.entity_type}", aliases={entity_a.aliases}\n'
            f'Entity B: name="{entity_b.name}", type="{entity_b.entity_type}", aliases={entity_b.aliases}\n'
            "Respond with is_same_entity (true/false) and brief reasoning."
        )
        try:
            result, _ = await self.llm.extract(
                text=prompt,
                system_prompt="You are an entity deduplication assistant. Decide if two entity mentions refer to the same real-world entity.",
                response_model=EntityMatchResult,
                max_tokens=256,
            )
            return result.is_same_entity
        except Exception:
            log.warning("dedup_llm_check_failed", entity_a=entity_a.name, entity_b=entity_b.name)
            return False


# ---------------------------------------------------------------------------
# Dedup v2 — batch-oriented, no threshold gate
# ---------------------------------------------------------------------------

_STRIP_CHARS = " _-.,;:()[]{}'\""  # characters to strip from names before trigram comparison


def _stripped_name(name: str) -> str:
    """Normalize a name for trigram comparison: lowercase, strip punctuation."""
    return name.lower().strip(_STRIP_CHARS)


def compute_composite_score(
    entity_a: EntityWithContext,
    entity_b: EntityWithContext,
    cosine_sim: float,
    same_run: bool,
    same_owner: bool,
) -> float:
    """Compute a composite similarity score for ordering entity pairs in a batch.

    Weights:
      0.4 * cosine(embedding_a, embedding_b)   — semantic similarity
      0.3 * trigram_similarity(name_a, name_b) — string similarity on normalized names
      0.2 * co_event_score                     — 1.0 if same extraction_run_id, else 0.0
      0.1 * shared_owner_score                 — 1.0 if same "owner" claim, else 0.0

    The score is used ONLY for sorting — not as a filter.
    """
    from rapidfuzz import fuzz

    trigram_sim = fuzz.ratio(_stripped_name(entity_a.name), _stripped_name(entity_b.name)) / 100.0
    co_event = 1.0 if same_run else 0.0
    shared_owner = 1.0 if same_owner else 0.0

    return 0.4 * cosine_sim + 0.3 * trigram_sim + 0.2 * co_event + 0.1 * shared_owner


def _get_owner_claim(entity: EntityWithContext) -> str | None:
    """Extract the 'owner' claim value from entity claims, if present."""
    for claim in entity.claims:
        if isinstance(claim, dict) and claim.get("predicate") == "owner":
            return str(claim.get("value", ""))
    return None


def _get_extraction_run_id(entity: EntityWithContext) -> str | None:
    """Extract extraction_run_id from entity properties, if present.

    NOTE: EntityWithContext does not carry extraction_run_id as a first-class field;
    the IntegratorEngine copies it into entity.properties["extraction_run_id"] when
    building EntityWithContext from the ORM model.  If that key is absent (e.g. for
    entities created before the pipeline was updated), this returns None gracefully —
    the co-event signal is simply omitted from the composite score.
    """
    return entity.properties.get("extraction_run_id")


def assemble_batches(
    entities: list[EntityWithContext],
    embeddings: dict[uuid.UUID, list[float]],
    *,
    batch_size: int = 9,
) -> list[list[EntityWithContext]]:
    """Group entities by type and assemble batches of at most batch_size.

    Within each type group, entities are sorted by their pairwise composite score to keep
    the most similar entities in the same batch. Uses a greedy approach: build a score
    matrix, then sort by max composite similarity to a reference entity.

    Only entity types with >= 2 entities produce batches (single-entity types have no
    dedup candidates).

    Returns a list of batches (each batch is a list of EntityWithContext).
    No cross-type batches are ever produced.
    """
    # Group by entity_type
    by_type: dict[str, list[EntityWithContext]] = {}
    for entity in entities:
        by_type.setdefault(entity.entity_type, []).append(entity)

    all_batches: list[list[EntityWithContext]] = []

    def _max_composite_for_group(
        entity: EntityWithContext,
        grp: list[EntityWithContext],
        embs: dict[uuid.UUID, list[float]],
    ) -> float:
        """Return the highest composite score between `entity` and any peer in `grp`."""
        emb_a = embs.get(entity.id)
        best = 0.0
        owner_a = _get_owner_claim(entity)
        run_a = _get_extraction_run_id(entity)
        for other in grp:
            if other.id == entity.id:
                continue
            emb_b = embs.get(other.id)
            cosine = _cosine_similarity(emb_a, emb_b) if (emb_a and emb_b) else 0.0
            owner_b = _get_owner_claim(other)
            run_b = _get_extraction_run_id(other)
            score = compute_composite_score(
                entity_a=entity,
                entity_b=other,
                cosine_sim=cosine,
                same_run=(run_a is not None and run_a == run_b),
                same_owner=(owner_a is not None and owner_a == owner_b),
            )
            best = max(best, score)
        return best

    for _entity_type, group in by_type.items():
        if len(group) < 2:
            # Single entity — nothing to dedup
            continue

        # Sort by descending max composite score so similar entities cluster together
        sorted_group = sorted(
            group,
            key=lambda e: _max_composite_for_group(e, group, embeddings),
            reverse=True,
        )

        # Split into batches of batch_size
        type_batches: list[list[EntityWithContext]] = []
        for i in range(0, len(sorted_group), batch_size):
            chunk = sorted_group[i : i + batch_size]
            if len(chunk) >= 2:
                type_batches.append(chunk)
            elif len(chunk) == 1 and type_batches:
                # Trailing 1-entity chunk: rebalance the last two batches to avoid dropping.
                # Merge the last batch with this singleton and re-split evenly.
                combined = type_batches[-1] + chunk
                mid = len(combined) // 2
                type_batches[-1] = combined[:mid]
                type_batches.append(combined[mid:])

        all_batches.extend(type_batches)

    return all_batches


_DEDUP_SYSTEM_PROMPT = (
    "You are an expert entity deduplication system for a corporate knowledge graph. "
    "Your task is to identify which entities represent the same real-world object. "
    "Be conservative: only merge when you are confident. "
    "Return only duplicates you are certain about."
)


def _build_dedup_prompt(entities: list[EntityWithContext], entity_type: str) -> str:
    """Build the focused dedup prompt for a batch of entities."""
    n = len(entities)
    rows: list[str] = []
    for i, e in enumerate(entities):
        top_claims = "; ".join(f"{c.get('predicate')}={c.get('value')}" for c in e.claims[:3] if isinstance(c, dict))
        aliases_str = ", ".join(e.aliases[:5]) if e.aliases else ""
        rows.append(f"  {i + 1}. id={e.id}  name={e.name!r}  aliases=[{aliases_str}]  top_claims=[{top_claims}]")

    batch_table = "\n".join(rows)

    return (
        f"You are an entity deduplication expert.\n\n"
        f"## Task\n"
        f'Given these {n} entities of type "{entity_type}", identify duplicates.\n'
        f"Two entities are duplicates if they refer to the same real-world thing, even with:\n"
        f"- Different spelling, abbreviations, transliterations\n"
        f"- One in Russian, one in Latin script\n"
        f"- Different levels of detail (short name vs full legal name)\n\n"
        f"## For each duplicate group, provide:\n"
        f"- The canonical name (best/clearest name)\n"
        f"- A merged description (synthesize from both)\n"
        f"- Which entity to keep (winner) and which to merge into it (losers)\n\n"
        f"## Entities\n"
        f"{batch_table}\n\n"
        f"Return a DedupResult with groups (may be empty if no duplicates found)."
    )


class DeduplicatorV2:
    """Batch-oriented entity deduplicator (dedup v2).

    Replaces the threshold-gated pair approach with:
    1. assemble_batches — group by type, sort by composite signal, chunk into N=9
    2. LLM batch call — focused prompt returns DedupResult (list of MergeGroups)
    3. execute_batches — apply MergeGroups: winner rewrite + loser soft-delete
    """

    def __init__(self, llm, *, batch_size: int = 9) -> None:
        self.llm = llm
        self.batch_size = batch_size

    async def execute_batches(
        self,
        batches: list[list[EntityWithContext]],
        entity_type: str,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        entity_repo,
        session,
        action_repo,
    ) -> tuple[int, list[str]]:
        """Call LLM for each batch, then apply MergeGroups.

        Returns (total_merged, merge_signatures) where merge_signatures is a list of
        strings like "merge:<winner_id>:[<loser_ids>]" for use in cycle detection hashing.
        """
        from alayaos_core.extraction.integrator.schemas import DedupResult

        total_merged = 0
        merge_signatures: list[str] = []
        for batch in batches:
            prompt = _build_dedup_prompt(batch, entity_type)
            try:
                dedup_result, _ = await self.llm.extract(
                    text=prompt,
                    system_prompt=_DEDUP_SYSTEM_PROMPT,
                    response_model=DedupResult,
                    max_tokens=1024,
                )
            except Exception:
                log.warning("dedup_v2_llm_failed", entity_type=entity_type, batch_size=len(batch))
                continue

            if not dedup_result.groups:
                continue

            # Build entity_id → EntityWithContext lookup for validation
            batch_ids: set[uuid.UUID] = {e.id for e in batch}

            for group in dedup_result.groups:
                # Guard: winner and losers must be in this batch
                if group.winner_id not in batch_ids:
                    log.warning("dedup_v2_winner_not_in_batch", winner_id=str(group.winner_id))
                    continue
                valid_loser_ids = [lid for lid in group.loser_ids if lid in batch_ids and lid != group.winner_id]
                if not valid_loser_ids:
                    continue

                merged = await self._apply_merge_group(
                    winner_id=group.winner_id,
                    loser_ids=valid_loser_ids,
                    merged_name=group.merged_name,
                    merged_description=group.merged_description,
                    merged_aliases=group.merged_aliases,
                    confidence=group.confidence,
                    rationale=group.rationale,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    entity_repo=entity_repo,
                    session=session,
                    action_repo=action_repo,
                )
                total_merged += merged
                if merged > 0:
                    sig = f"merge:{group.winner_id}:{sorted(str(lid) for lid in valid_loser_ids)}"
                    merge_signatures.append(sig)

        return total_merged, merge_signatures

    async def _apply_merge_group(
        self,
        winner_id: uuid.UUID,
        loser_ids: list[uuid.UUID],
        merged_name: str,
        merged_description: str,
        merged_aliases: list[str],
        confidence: float,
        rationale: str,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        entity_repo,
        session,
        action_repo,
    ) -> int:
        """Apply a single MergeGroup: rewrite winner, soft-delete losers, reassign FK refs."""
        from sqlalchemy import text

        winner = await entity_repo.get_by_id(winner_id)
        if winner is None:
            return 0

        # Snapshot winner before modification (for rollback/audit)
        before_snapshot = {
            "name": winner.name,
            "description": getattr(winner, "description", "") or "",
            "aliases": list(winner.aliases or []),
        }

        # Union all aliases: existing winner aliases + merged_aliases + loser names
        new_aliases = list(dict.fromkeys(list(winner.aliases or []) + list(merged_aliases)))

        # Rewrite winner
        await entity_repo.update(
            winner_id,
            name=merged_name,
            description=merged_description,
            aliases=new_aliases,
        )

        merged_count = 0
        for loser_id in loser_ids:
            loser = await entity_repo.get_by_id(loser_id)
            if loser is None:
                continue

            # Add loser's original name as alias on winner
            if loser.name and loser.name not in new_aliases:
                new_aliases = list(dict.fromkeys([*new_aliases, loser.name]))
                await entity_repo.update(winner_id, aliases=new_aliases)

            # --- Collect IDs BEFORE mutation (mirrors WHERE clauses below) ---

            # Claims that will be moved
            claim_result = await session.execute(
                text("SELECT id FROM l2_claims WHERE entity_id = :b_id AND workspace_id = :ws_id"),
                {"b_id": loser_id, "ws_id": workspace_id},
            )
            moved_claim_ids = [str(r[0]) for r in claim_result.fetchall()]

            # Relations where loser is source (that will be reassigned, not self-ref deleted)
            rel_src_result = await session.execute(
                text(
                    "SELECT id FROM l1_relations"
                    " WHERE source_entity_id = :b_id AND target_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            moved_relation_source_ids = [str(r[0]) for r in rel_src_result.fetchall()]

            # Self-ref b→a relations that will be deleted
            self_ref_ba_result = await session.execute(
                text(
                    "SELECT id FROM l1_relations"
                    " WHERE source_entity_id = :b_id AND target_entity_id = :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            deleted_self_ref_ba_ids = [str(r[0]) for r in self_ref_ba_result.fetchall()]

            # Relations where loser is target (that will be reassigned, not self-ref deleted)
            rel_tgt_result = await session.execute(
                text(
                    "SELECT id FROM l1_relations"
                    " WHERE target_entity_id = :b_id AND source_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            moved_relation_target_ids = [str(r[0]) for r in rel_tgt_result.fetchall()]

            # Self-ref a→b relations that will be deleted
            self_ref_ab_result = await session.execute(
                text(
                    "SELECT id FROM l1_relations"
                    " WHERE source_entity_id = :a_id AND target_entity_id = :b_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            deleted_self_ref_ab_ids = [str(r[0]) for r in self_ref_ab_result.fetchall()]
            deleted_self_ref_relation_ids = deleted_self_ref_ba_ids + deleted_self_ref_ab_ids

            # Vector chunks that will be moved
            chunk_result = await session.execute(
                text(
                    "SELECT id FROM vector_chunks"
                    " WHERE source_id = :b_id AND source_type = 'entity' AND workspace_id = :ws_id"
                ),
                {"b_id": loser_id, "ws_id": workspace_id},
            )
            moved_chunk_ids = [str(r[0]) for r in chunk_result.fetchall()]

            # --- Execute mutations ---

            # Reassign claims from loser to winner
            await session.execute(
                text("UPDATE l2_claims SET entity_id = :a_id WHERE entity_id = :b_id AND workspace_id = :ws_id"),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )

            # Reassign relations where loser is source (skip would-be self-refs)
            await session.execute(
                text(
                    "UPDATE l1_relations SET source_entity_id = :a_id"
                    " WHERE source_entity_id = :b_id AND target_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            # Delete b→a relations that would become self-referential
            await session.execute(
                text(
                    "DELETE FROM l1_relations"
                    " WHERE source_entity_id = :b_id AND target_entity_id = :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )

            # Reassign relations where loser is target (skip would-be self-refs)
            await session.execute(
                text(
                    "UPDATE l1_relations SET target_entity_id = :a_id"
                    " WHERE target_entity_id = :b_id AND source_entity_id != :a_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )
            # Delete a→b relations that would become self-referential
            await session.execute(
                text(
                    "DELETE FROM l1_relations"
                    " WHERE source_entity_id = :a_id AND target_entity_id = :b_id"
                    " AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )

            # Reassign vector chunks
            await session.execute(
                text(
                    "UPDATE vector_chunks SET source_id = :a_id"
                    " WHERE source_id = :b_id AND source_type = 'entity' AND workspace_id = :ws_id"
                ),
                {"a_id": winner_id, "b_id": loser_id, "ws_id": workspace_id},
            )

            # Duplicate relations caused per-loser by the FK moves just made: scope dedup pass to
            # this single loser's winner to yield accurate per-loser audit fidelity.
            dedup_result = await session.execute(
                text(
                    "DELETE FROM l1_relations"
                    " WHERE workspace_id = :ws_id"
                    " AND id IN ("
                    "   SELECT id FROM ("
                    "     SELECT id,"
                    "       ROW_NUMBER() OVER ("
                    "         PARTITION BY source_entity_id, target_entity_id, relation_type"
                    "         ORDER BY created_at ASC"
                    "       ) AS row_number"
                    "     FROM l1_relations"
                    "     WHERE workspace_id = :ws_id"
                    "       AND (source_entity_id = :winner_id OR target_entity_id = :winner_id)"
                    "   ) ranked"
                    "   WHERE row_number > 1"
                    " )"
                    " RETURNING id"
                ),
                {"ws_id": workspace_id, "winner_id": winner_id},
            )
            deduplicated_rows = dedup_result.fetchall()
            deduplicated_relation_ids = [str(r[0]) for r in deduplicated_rows]

            # Soft-delete loser with provenance
            loser_props = dict(loser.properties or {})
            loser_props["merged_into"] = str(winner_id)
            await entity_repo.update(loser_id, is_deleted=True, properties=loser_props)

            # v2 inverse payload (additive on top of existing keys)
            v2_payload = {
                "moved_claim_ids": moved_claim_ids,
                "moved_relation_source_ids": moved_relation_source_ids,
                "moved_relation_target_ids": moved_relation_target_ids,
                "moved_chunk_ids": moved_chunk_ids,
                "deleted_self_ref_relation_ids": deleted_self_ref_relation_ids,
                "deduplicated_relation_ids": deduplicated_relation_ids,
                "winner_before": before_snapshot,
            }

            # Record audit action (best-effort — failure doesn't abort merge)
            if action_repo is not None:
                try:
                    from alayaos_core.schemas.integrator_action import IntegratorActionCreate

                    await action_repo.create(
                        workspace_id=workspace_id,
                        data=IntegratorActionCreate(
                            run_id=run_id,
                            action_type="merge",
                            entity_id=winner_id,
                            params={
                                "name": merged_name,
                                "description": merged_description,
                                "aliases": new_aliases,
                            },
                            targets=[str(loser_id)],
                            inverse={
                                "action": "unmerge",
                                "loser_id": str(loser_id),
                                **v2_payload,
                            },
                            confidence=confidence,
                            rationale=rationale,
                            snapshot_schema_version=2,
                        ),
                    )
                except Exception:
                    log.error(
                        "merge_audit_write_failed",
                        winner_id=str(winner_id),
                        loser_id=str(loser_id),
                        exc_info=True,
                    )

            merged_count += 1

        return merged_count
