"""EntityDeduplicator — 3-tier entity deduplication using rapidfuzz + transliteration + LLM."""

from __future__ import annotations

import structlog

from alayaos_core.extraction.integrator.schemas import DuplicatePair, EntityMatchResult, EntityWithContext
from alayaos_core.extraction.resolver import transliterate_name

log = structlog.get_logger()

# Minimum name length for fuzzy matching (short names are too unreliable)
_MIN_NAME_LENGTH = 4


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

        # Build name→entity mapping
        names = [e.name for e in scoreable]
        id_by_name: dict[str, EntityWithContext] = {e.name: e for e in scoreable}

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

            for candidate_name, score_raw, _idx in matches:
                candidate = id_by_name[candidate_name]

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
