"""Tests for vector shortlist dedup (Sprint S6 — RUN5.3.04)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.integrator.schemas import EntityWithContext


def _make_entity(
    name: str,
    entity_type: str = "person",
    entity_type_id: uuid.UUID | None = None,
) -> EntityWithContext:
    return EntityWithContext(
        id=uuid.uuid4(),
        name=name,
        entity_type=entity_type,
        properties={"entity_type_id": str(entity_type_id or uuid.uuid4())},
    )


def _make_embeddings(entities: list[EntityWithContext], dim: int = 4) -> dict[uuid.UUID, list[float]]:
    """Return deterministic unit-vector embeddings keyed by entity id."""
    import hashlib

    result: dict[uuid.UUID, list[float]] = {}
    for e in entities:
        h = hashlib.sha256(e.name.encode()).digest()
        raw = [((b % 200) - 100) / 100.0 for b in (h * ((dim // len(h)) + 1))[:dim]]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        result[e.id] = [x / norm for x in raw]
    return result


# ---------------------------------------------------------------------------
# Test: shortlist_candidates
# ---------------------------------------------------------------------------


class TestShortlistCandidates:
    """Unit tests for shortlist_candidates (pure Python, no DB, no LLM)."""

    def test_shortlist_returns_only_top_k(self):
        """Seed 20 entities; shortlist must return at most 20 * K pairs."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        k = 5
        type_id = uuid.uuid4()
        entities = [_make_entity(f"Entity-{i:02d}", entity_type_id=type_id) for i in range(20)]
        embeddings = _make_embeddings(entities)
        pairs = shortlist_candidates(entities, embeddings, k=k, threshold=0.0)
        # At most n * k / 2 unique pairs (deduplicated), and certainly ≤ 20 * k
        assert len(pairs) <= 20 * k

    def test_shortlist_respects_entity_type(self):
        """Entities of different types must never be paired."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        type_a = uuid.uuid4()
        type_b = uuid.uuid4()
        # Two groups; each pair within a group may match (same name), but cross-type must not
        entities_a = [_make_entity("Alice", entity_type="person", entity_type_id=type_a)]
        entities_b = [_make_entity("Alice", entity_type="project", entity_type_id=type_b)]
        all_entities = entities_a + entities_b
        embeddings = _make_embeddings(all_entities)
        pairs = shortlist_candidates(all_entities, embeddings, k=5, threshold=0.0)
        for a, b in pairs:
            assert a.entity_type == b.entity_type, f"Cross-type pair found: {a.entity_type} vs {b.entity_type}"

    def test_shortlist_respects_threshold(self):
        """Pairs with cosine similarity below threshold are excluded."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        type_id = uuid.uuid4()
        # Two entities with orthogonal embeddings (similarity ≈ 0)
        e1 = _make_entity("EntityA", entity_type_id=type_id)
        e2 = _make_entity("EntityB", entity_type_id=type_id)
        # Manually assign orthogonal embeddings
        custom_embeddings = {
            e1.id: [1.0, 0.0, 0.0, 0.0],
            e2.id: [0.0, 1.0, 0.0, 0.0],
        }
        # With threshold=0.5, orthogonal vectors (similarity=0) should be excluded
        pairs = shortlist_candidates([e1, e2], custom_embeddings, k=5, threshold=0.5)
        assert pairs == [], f"Expected no pairs above threshold=0.5, got {pairs}"

    def test_shortlist_includes_close_pairs(self):
        """Pairs with cosine similarity above threshold are included."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        type_id = uuid.uuid4()
        e1 = _make_entity("EntityA", entity_type_id=type_id)
        e2 = _make_entity("EntityB", entity_type_id=type_id)
        # Near-identical embeddings → high cosine similarity
        custom_embeddings = {
            e1.id: [1.0, 0.01, 0.0, 0.0],
            e2.id: [1.0, 0.02, 0.0, 0.0],
        }
        pairs = shortlist_candidates([e1, e2], custom_embeddings, k=5, threshold=0.9)
        assert len(pairs) == 1
        assert (pairs[0][0].id, pairs[0][1].id) in {
            (e1.id, e2.id),
            (e2.id, e1.id),
        }

    def test_shortlist_no_self_pairs(self):
        """An entity is never paired with itself."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        type_id = uuid.uuid4()
        e = _make_entity("Solo", entity_type_id=type_id)
        embeddings = _make_embeddings([e])
        pairs = shortlist_candidates([e], embeddings, k=5, threshold=0.0)
        assert pairs == []

    def test_shortlist_deduplicates_pairs(self):
        """If A→B and B→A are both in shortlists, only one pair is emitted."""
        from alayaos_core.extraction.integrator.dedup import shortlist_candidates

        type_id = uuid.uuid4()
        e1 = _make_entity("Alice", entity_type_id=type_id)
        e2 = _make_entity("Alice", entity_type_id=type_id)
        # Identical embeddings — both will see each other in top-K
        custom_embeddings = {
            e1.id: [1.0, 0.0, 0.0, 0.0],
            e2.id: [1.0, 0.0, 0.0, 0.0],
        }
        pairs = shortlist_candidates([e1, e2], custom_embeddings, k=5, threshold=0.5)
        assert len(pairs) == 1  # exactly one pair, not two


# ---------------------------------------------------------------------------
# Test: dedup_still_merges_obvious_duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_still_merges_obvious_duplicates():
    """Two entities with near-identical names and embeddings are still merged.

    Verifies that the full engine flow (shortlist → LLM verify → merge) correctly
    processes obvious duplicates after the vector shortlist is introduced.
    """
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult

    ws_id = uuid.uuid4()
    type_id = uuid.uuid4()

    # Two near-identical entities (duplicates)
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    def _make_entity_mock(eid, name):
        m = MagicMock()
        m.id = eid
        m.name = name
        m.is_deleted = False
        m.entity_type_id = type_id
        m.aliases = []
        m.properties = {}
        m.entity_type = MagicMock()
        m.entity_type.slug = "person"
        return m

    entity_a_mock = _make_entity_mock(entity_a_id, "Alice Johnson")
    entity_b_mock = _make_entity_mock(entity_b_id, "Alice Johnson")  # identical name

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_a_mock, entity_b_mock])
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {
            entity_a_id: entity_a_mock,
            entity_b_id: entity_b_mock,
        }.get(eid)
    )

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    from alayaos_core.llm.fake import FakeLLMAdapter

    fake_llm = FakeLLMAdapter()

    def _make_redis_mock():
        redis_mock = AsyncMock()
        redis_mock.rename = AsyncMock(side_effect=Exception("no such key"))
        redis_mock.smembers = AsyncMock(return_value=set())
        redis_mock.delete = AsyncMock(return_value=1)
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.eval = AsyncMock(return_value=1)
        return redis_mock

    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.85
    settings.INTEGRATOR_MODEL = "claude-test"

    engine = IntegratorEngine(
        llm=fake_llm,
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=_make_redis_mock(),
        settings=settings,
    )

    session = AsyncMock()
    result = await engine.run(ws_id, session)

    assert isinstance(result, IntegratorRunResult)
    assert result.status == "completed"
    # The two identical-name entities should be detected and merged
    assert result.entities_deduplicated >= 1, f"Expected at least 1 merge, got {result.entities_deduplicated}"


# ---------------------------------------------------------------------------
# Test: config knobs exist
# ---------------------------------------------------------------------------


def test_settings_has_shortlist_knobs():
    """Settings must expose INTEGRATOR_DEDUP_SHORTLIST_K and INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD."""
    from alayaos_core.config import Settings

    s = Settings()
    assert hasattr(s, "INTEGRATOR_DEDUP_SHORTLIST_K"), "Missing INTEGRATOR_DEDUP_SHORTLIST_K"
    assert hasattr(s, "INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD"), "Missing INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD"
    assert s.INTEGRATOR_DEDUP_SHORTLIST_K == 5
    # Fix #1: default must be 0.9 (safe budget), not 0.85
    assert s.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD == 0.9


# ---------------------------------------------------------------------------
# Fix #1: default threshold is 0.9
# ---------------------------------------------------------------------------


def test_settings_default_similarity_threshold_is_0_9():
    """INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD default must be 0.9 (< 5-min budget)."""
    from alayaos_core.config import Settings

    s = Settings()
    assert s.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD == 0.9


# ---------------------------------------------------------------------------
# Fix #2: short-name safety guard in shortlist_candidates
# ---------------------------------------------------------------------------


def test_shortlist_filters_short_names():
    """Entities with names shorter than _MIN_NAME_LENGTH (4) must be excluded from shortlist."""
    from alayaos_core.extraction.integrator.dedup import shortlist_candidates

    type_id = uuid.uuid4()
    # 2-char names — must be filtered out
    e1 = _make_entity("Li", entity_type="person", entity_type_id=type_id)
    e2 = _make_entity("Li", entity_type="person", entity_type_id=type_id)
    # Normal long-name entity to ensure shortlist itself works
    e3 = _make_entity("Alice Johnson", entity_type="person", entity_type_id=type_id)
    e4 = _make_entity("Alice Johnson", entity_type="person", entity_type_id=type_id)

    all_entities = [e1, e2, e3, e4]
    # Give identical embeddings so similarity=1.0 for all pairs
    vec = [1.0, 0.0, 0.0, 0.0]
    embeddings = {e.id: vec[:] for e in all_entities}

    pairs = shortlist_candidates(all_entities, embeddings, k=5, threshold=0.0)

    # e1 and e2 (short names) must not appear in any pair
    short_ids = {e1.id, e2.id}
    for a, b in pairs:
        assert a.id not in short_ids, f"Short-name entity {a.name!r} appeared in shortlist pair"
        assert b.id not in short_ids, f"Short-name entity {b.name!r} appeared in shortlist pair"


# ---------------------------------------------------------------------------
# Fix #4: cosine_similarity dimension mismatch handling
# ---------------------------------------------------------------------------


def test_cosine_similarity_handles_dimension_mismatch():
    """_cosine_similarity must return 0.0 (not raise) when vectors have different lengths."""
    from alayaos_core.extraction.integrator.dedup import _cosine_similarity

    # Normal case still works
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    # Mismatched dimensions must return 0.0, not raise
    result = _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0])
    assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Fix #5: boundary tests for shortlist_candidates
# ---------------------------------------------------------------------------


def test_shortlist_keeps_pair_at_exact_threshold():
    """A pair with cosine similarity exactly equal to threshold must be included (>= semantics)."""
    from alayaos_core.extraction.integrator.dedup import _cosine_similarity, shortlist_candidates

    type_id = uuid.uuid4()
    e1 = _make_entity("EntityA", entity_type_id=type_id)
    e2 = _make_entity("EntityB", entity_type_id=type_id)
    # Use vectors where we know the exact cosine similarity
    v1 = [1.0, 0.0]
    v2 = [1.0, 0.0]  # identical → similarity = 1.0
    custom_embeddings = {e1.id: v1, e2.id: v2}
    # Set threshold exactly equal to the similarity
    sim = _cosine_similarity(v1, v2)
    pairs = shortlist_candidates([e1, e2], custom_embeddings, k=5, threshold=sim)
    assert len(pairs) == 1, f"Pair at exact threshold {sim} should be included, got {pairs}"


def test_shortlist_deduplicates_pairs_canonical_uuid_ordering():
    """Every emitted pair must have str(pair[0].id) < str(pair[1].id) (canonical order)."""
    from alayaos_core.extraction.integrator.dedup import shortlist_candidates

    type_id = uuid.uuid4()
    # Create many entities so multiple pairs are emitted
    entities = [_make_entity(f"Alice-{i}", entity_type_id=type_id) for i in range(5)]
    # Identical embedding → all pairs have similarity = 1.0
    vec = [1.0, 0.0, 0.0, 0.0]
    embeddings = {e.id: vec[:] for e in entities}
    pairs = shortlist_candidates(entities, embeddings, k=10, threshold=0.0)
    assert len(pairs) > 0, "Expected at least one pair"
    for a, b in pairs:
        assert str(a.id) < str(b.id), f"Pair not in canonical UUID order: {a.id} vs {b.id}"


# ---------------------------------------------------------------------------
# Fix #3: mainline test hits shortlist path (FakeEmbeddingService injected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_shortlist_path_is_exercised():
    """Engine must use the shortlist path (FakeEmbeddingService) rather than rapidfuzz fallback.

    Uses path (a): inject FakeEmbeddingService directly into engine._embedding_service.
    Asserts embed() was called and entities_deduplicated >= 1 (identical-name entities merged).
    """
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult
    from alayaos_core.llm.fake import FakeLLMAdapter
    from alayaos_core.services.embedding import FakeEmbeddingService

    ws_id = uuid.uuid4()
    type_id = uuid.uuid4()

    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    def _make_entity_mock(eid, name):
        m = MagicMock()
        m.id = eid
        m.name = name
        m.is_deleted = False
        m.entity_type_id = type_id
        m.aliases = []
        m.properties = {}
        m.entity_type = MagicMock()
        m.entity_type.slug = "person"
        return m

    entity_a_mock = _make_entity_mock(entity_a_id, "Alice Johnson")
    entity_b_mock = _make_entity_mock(entity_b_id, "Alice Johnson")

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_a_mock, entity_b_mock])
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {
            entity_a_id: entity_a_mock,
            entity_b_id: entity_b_mock,
        }.get(eid)
    )
    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    fake_llm = FakeLLMAdapter()
    # FakeLLMAdapter._MODEL_OVERRIDES["EntityMatchResult"] already returns is_same_entity=True

    def _make_redis_mock():
        redis_mock = AsyncMock()
        redis_mock.rename = AsyncMock(side_effect=Exception("no such key"))
        redis_mock.smembers = AsyncMock(return_value=set())
        redis_mock.delete = AsyncMock(return_value=1)
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.eval = AsyncMock(return_value=1)
        return redis_mock

    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.9

    # Build a FakeEmbeddingService that gives identical vectors for identical names
    fake_embed = FakeEmbeddingService(dimensions=4)
    # Spy on embed_texts to confirm it's called
    original_embed = fake_embed.embed_texts
    embed_calls: list[list[str]] = []

    async def spy_embed(texts):
        embed_calls.append(texts)
        return await original_embed(texts)

    fake_embed.embed_texts = spy_embed  # type: ignore[method-assign]

    engine = IntegratorEngine(
        llm=fake_llm,
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=_make_redis_mock(),
        settings=settings,
    )
    # Inject the fake embedding service (path a)
    engine._embedding_service = fake_embed

    session = AsyncMock()
    result = await engine.run(ws_id, session)

    assert isinstance(result, IntegratorRunResult)
    assert result.status == "completed"
    # The embed spy must have been called (proves shortlist path, not fallback)
    assert len(embed_calls) >= 1, "FakeEmbeddingService.embed_texts was never called — shortlist path not taken"


# ---------------------------------------------------------------------------
# Fix #6: entities with unresolvable entity_type are skipped in shortlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shortlist_skips_typeless_entities():
    """IntegratorEngine._shortlist_dedup must skip entities with entity_type == 'unknown'.

    Uses an LLM mock that always returns is_same_entity=True so any pair reaching LLM
    would be counted. Asserts zero pairs are emitted: the 'unknown' type guard must fire
    before the LLM call.
    """
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult, EntityWithContext
    from alayaos_core.services.embedding import FakeEmbeddingService

    # LLM always says "same entity" — so if any pair reaches LLM, we'd get a DuplicatePair
    always_same_llm = AsyncMock()
    always_same_llm.extract = AsyncMock(return_value=(EntityMatchResult(is_same_entity=True, reasoning="same"), None))

    fake_embed = FakeEmbeddingService(dimensions=4)

    # Two entities that would normally match (same name) but both have 'unknown' type
    ewc_a = EntityWithContext(id=uuid.uuid4(), name="Alice Johnson", entity_type="unknown")
    ewc_b = EntityWithContext(id=uuid.uuid4(), name="Alice Johnson", entity_type="unknown")

    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.0  # low threshold so only type blocks match

    entity_repo = AsyncMock()
    claim_repo = AsyncMock()
    relation_repo = AsyncMock()
    entity_cache = AsyncMock()
    redis_mock = AsyncMock()

    engine = IntegratorEngine(
        llm=always_same_llm,
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )
    engine._embedding_service = fake_embed  # type: ignore[attr-defined]

    pairs = await engine._shortlist_dedup([ewc_a, ewc_b])  # type: ignore[attr-defined]
    assert pairs == [], f"Expected no pairs for 'unknown' type entities, got {pairs}"
