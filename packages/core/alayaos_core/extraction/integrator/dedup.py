"""EntityDeduplicator — 3-tier entity deduplication using rapidfuzz + transliteration + LLM.

Sprint S6 adds a vector-shortlist pass: instead of comparing every O(n²) pair with the LLM,
we first embed entity names in Python (fast, no DB), group by entity_type, and retain only the
top-K nearest neighbours per entity above a cosine-similarity threshold.  Only those pairs go
to the (slow) LLM verifier.
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

        # Use index-based lookup to handle same-name entities correctly
        names = [e.name for e in scoreable]

        pairs: list[DuplicatePair] = []
        seen: set[frozenset] = set()

        from rapidfuzz.distance import JaroWinkler

        for entity in scoreable:
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
                candidate = scoreable[idx]

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
