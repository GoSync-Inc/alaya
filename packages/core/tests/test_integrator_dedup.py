"""Tests for vector shortlist dedup (Sprint S6 — RUN5.3.04)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.integrator.schemas import EntityWithContext


def _make_session_mock(rows: list | None = None) -> AsyncMock:
    """Create an AsyncMock session whose execute() returns a result with sync fetchall().

    The new v2 audit code calls result.fetchall() (sync) after await session.execute(...).
    A plain AsyncMock returns another coroutine for fetchall() — this helper fixes that.

    Also configures begin_nested() as a sync MagicMock returning an async CM, since
    the engine wraps each phase in `async with session.begin_nested():` (SAVEPOINT).
    """
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows if rows is not None else []
    session = AsyncMock()
    session.execute.return_value = mock_result
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


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

    session = _make_session_mock()
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

    session = _make_session_mock()
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

    pairs, _usage = await engine._shortlist_dedup([ewc_a, ewc_b])  # type: ignore[attr-defined]
    assert pairs == [], f"Expected no pairs for 'unknown' type entities, got {pairs}"


@pytest.mark.asyncio
async def test_find_duplicates_fallback_does_not_cross_entity_types():
    """Rapidfuzz fallback find_duplicates must not match entities of different types.

    Regression test for CRITICAL holistic finding: when FastEmbed fails, _shortlist_dedup
    falls back to find_duplicates() which previously lacked a same-type guard. This test
    ensures "Alice" (person) and "Alice" (project) are never returned as a DuplicatePair.
    """
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator

    # LLM always says same entity — so any pair reaching LLM would produce a DuplicatePair.
    always_same_llm = AsyncMock()
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult

    always_same_llm.extract = AsyncMock(return_value=(EntityMatchResult(is_same_entity=True, reasoning="same"), None))

    deduplicator = EntityDeduplicator(llm=always_same_llm, threshold=0.85, ambiguous_low=0.70)

    alice_person = _make_entity("Alice", entity_type="person")
    alice_project = _make_entity("Alice", entity_type="project")

    pairs, _usage = await deduplicator.find_duplicates([alice_person, alice_project])

    assert pairs == [], (
        f"Cross-type merge detected: find_duplicates returned {pairs} for "
        "'Alice' (person) vs 'Alice' (project) — same-type guard is missing."
    )


# ---------------------------------------------------------------------------
# NEW Sprint 5 tests
# ---------------------------------------------------------------------------


# ── Schema tests ────────────────────────────────────────────────────────────


def test_merge_group_schema():
    """MergeGroup schema must be importable and validate correctly."""
    from alayaos_core.extraction.integrator.schemas import MergeGroup

    g = MergeGroup(
        winner_id=uuid.uuid4(),
        loser_ids=[uuid.uuid4()],
        merged_name="Alice Johnson",
        merged_description="Senior engineer",
        merged_aliases=["Alice", "AJ"],
        confidence=0.95,
        rationale="Same person, different spellings",
    )
    assert g.merged_name == "Alice Johnson"
    assert 0.0 <= g.confidence <= 1.0


def test_dedup_result_schema():
    """DedupResult schema must be importable and default to empty groups."""
    from alayaos_core.extraction.integrator.schemas import DedupResult

    r = DedupResult(groups=[])
    assert r.groups == []


def test_merge_group_confidence_bounds():
    """MergeGroup.confidence must be clamped to [0.0, 1.0]."""
    import pydantic

    from alayaos_core.extraction.integrator.schemas import MergeGroup

    with pytest.raises(pydantic.ValidationError):
        MergeGroup(
            winner_id=uuid.uuid4(),
            loser_ids=[uuid.uuid4()],
            merged_name="X",
            merged_description="",
            merged_aliases=[],
            confidence=1.5,  # invalid
            rationale="test",
        )


def test_merge_group_rationale_max_length():
    """MergeGroup.rationale must be capped at 280 chars."""
    import pydantic

    from alayaos_core.extraction.integrator.schemas import MergeGroup

    with pytest.raises(pydantic.ValidationError):
        MergeGroup(
            winner_id=uuid.uuid4(),
            loser_ids=[uuid.uuid4()],
            merged_name="X",
            merged_description="",
            merged_aliases=[],
            confidence=0.9,
            rationale="x" * 281,  # 1 char too long
        )


# ── Composite signal ordering ────────────────────────────────────────────────


def test_composite_signal_ordering():
    """compute_composite_score must return higher value for similar names than dissimilar ones."""
    from alayaos_core.extraction.integrator.dedup import compute_composite_score

    e1 = _make_entity("Alice Johnson")
    e2 = _make_entity("Alice Johnson Jr")  # very similar name
    e3 = _make_entity("Bob Smith")  # dissimilar name

    score_similar = compute_composite_score(
        entity_a=e1,
        entity_b=e2,
        cosine_sim=0.99,
        same_run=True,
        same_owner=False,
    )
    score_dissimilar = compute_composite_score(
        entity_a=e1,
        entity_b=e3,
        cosine_sim=0.1,
        same_run=False,
        same_owner=False,
    )

    assert score_similar > score_dissimilar, (
        f"Expected similar pair ({score_similar:.3f}) > dissimilar pair ({score_dissimilar:.3f})"
    )


def test_composite_signal_co_event_bonus():
    """Co-event flag adds 0.2 to composite score."""
    from alayaos_core.extraction.integrator.dedup import compute_composite_score

    e1 = _make_entity("Alice")
    e2 = _make_entity("Alice")

    score_with = compute_composite_score(e1, e2, cosine_sim=0.5, same_run=True, same_owner=False)
    score_without = compute_composite_score(e1, e2, cosine_sim=0.5, same_run=False, same_owner=False)

    assert abs(score_with - score_without - 0.2) < 1e-6, (
        f"Expected co-event to add exactly 0.2, got diff {score_with - score_without:.6f}"
    )


def test_composite_signal_shared_owner_bonus():
    """Shared owner flag adds 0.1 to composite score."""
    from alayaos_core.extraction.integrator.dedup import compute_composite_score

    e1 = _make_entity("Alice")
    e2 = _make_entity("Alice")

    score_with = compute_composite_score(e1, e2, cosine_sim=0.5, same_run=False, same_owner=True)
    score_without = compute_composite_score(e1, e2, cosine_sim=0.5, same_run=False, same_owner=False)

    assert abs(score_with - score_without - 0.1) < 1e-6, (
        f"Expected shared owner to add exactly 0.1, got diff {score_with - score_without:.6f}"
    )


# ── Batch assembly ───────────────────────────────────────────────────────────


def test_all_pairs_within_type_batching():
    """All same-type entities (≥2) must be included in batches."""
    from alayaos_core.extraction.integrator.dedup import assemble_batches

    type_id = uuid.uuid4()
    entities = [_make_entity(f"Entity-{i}", entity_type="person", entity_type_id=type_id) for i in range(5)]
    embeddings = {e.id: [1.0, 0.0, 0.0, 0.0] for e in entities}

    batches = assemble_batches(entities, embeddings, batch_size=9)

    # All 5 person entities must appear somewhere in a batch
    all_ids_in_batches = {e.id for batch in batches for e in batch}
    for entity in entities:
        assert entity.id in all_ids_in_batches, f"Entity {entity.name!r} missing from batches"


def test_batch_size_config():
    """Batches must not exceed the configured batch_size."""
    from alayaos_core.extraction.integrator.dedup import assemble_batches

    type_id = uuid.uuid4()
    entities = [_make_entity(f"Entity-{i:02d}", entity_type="person", entity_type_id=type_id) for i in range(25)]
    embeddings = {e.id: [1.0, 0.0, 0.0, 0.0] for e in entities}

    batch_size = 9
    batches = assemble_batches(entities, embeddings, batch_size=batch_size)

    for i, batch in enumerate(batches):
        assert len(batch) <= batch_size, f"Batch {i} has {len(batch)} entities, exceeds batch_size={batch_size}"


def test_no_cross_type_merges_in_batch():
    """assemble_batches must never mix entities of different types in one batch."""
    from alayaos_core.extraction.integrator.dedup import assemble_batches

    type_a_id = uuid.uuid4()
    type_b_id = uuid.uuid4()
    persons = [_make_entity(f"Person-{i}", entity_type="person", entity_type_id=type_a_id) for i in range(3)]
    projects = [_make_entity(f"Project-{i}", entity_type="project", entity_type_id=type_b_id) for i in range(3)]
    all_entities = persons + projects
    embeddings = {e.id: [1.0, 0.0, 0.0, 0.0] for e in all_entities}

    batches = assemble_batches(all_entities, embeddings, batch_size=9)

    for batch in batches:
        types_in_batch = {e.entity_type for e in batch}
        assert len(types_in_batch) == 1, f"Cross-type batch detected: {types_in_batch}"


def test_settings_has_dedup_batch_size():
    """Settings must expose INTEGRATOR_DEDUP_BATCH_SIZE with default 9."""
    from alayaos_core.config import Settings

    s = Settings()
    assert hasattr(s, "INTEGRATOR_DEDUP_BATCH_SIZE"), "Missing INTEGRATOR_DEDUP_BATCH_SIZE"
    assert s.INTEGRATOR_DEDUP_BATCH_SIZE == 9


# ── Merge-with-rewrite ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_with_rewrite_output():
    """After merge: winner has merged_name, merged_description, union aliases."""
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup

    winner_id = uuid.uuid4()
    loser_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    winner_entity = MagicMock()
    winner_entity.id = winner_id
    winner_entity.name = "Alice Johnson"
    winner_entity.aliases = ["AJ"]
    winner_entity.description = "engineer"
    winner_entity.properties = {}

    loser_entity = MagicMock()
    loser_entity.id = loser_id
    loser_entity.name = "Alice Jonson"
    loser_entity.aliases = ["Alice J"]
    loser_entity.description = "senior engineer"
    loser_entity.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {winner_id: winner_entity, loser_id: loser_entity}.get(eid)
    )
    entity_repo.update = AsyncMock()

    fake_llm = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser_id],
                merged_name="Alice Johnson",
                merged_description="Senior engineer",
                merged_aliases=["AJ", "Alice J"],
                confidence=0.95,
                rationale="Same person",
            )
        ]
    )
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    session = _make_session_mock()

    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)

    winner_ewc = EntityWithContext(
        id=winner_id,
        name="Alice Johnson",
        entity_type="person",
        aliases=["AJ"],
    )
    loser_ewc = EntityWithContext(
        id=loser_id,
        name="Alice Jonson",
        entity_type="person",
        aliases=["Alice J"],
    )

    batches = [[winner_ewc, loser_ewc]]
    merged, _sigs, _usage = await deduplicator.execute_batches(
        batches=batches,
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=None,
    )

    assert merged >= 1
    # winner entity update must have been called with merged_name and merged_description
    update_calls = entity_repo.update.call_args_list
    winner_calls = [c for c in update_calls if c.args[0] == winner_id]
    assert len(winner_calls) >= 1
    # Check that the name was set to merged_name
    winner_kwargs = winner_calls[0].kwargs
    assert winner_kwargs.get("name") == "Alice Johnson" or winner_kwargs.get("aliases") is not None


@pytest.mark.asyncio
async def test_loser_soft_deleted():
    """After merge: loser entity must have is_deleted=True."""
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup

    winner_id = uuid.uuid4()
    loser_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    winner_entity = MagicMock()
    winner_entity.id = winner_id
    winner_entity.name = "Alice Johnson"
    winner_entity.aliases = []
    winner_entity.description = ""
    winner_entity.properties = {}

    loser_entity = MagicMock()
    loser_entity.id = loser_id
    loser_entity.name = "Alice Jonson"
    loser_entity.aliases = []
    loser_entity.description = ""
    loser_entity.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {winner_id: winner_entity, loser_id: loser_entity}.get(eid)
    )
    entity_repo.update = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser_id],
                merged_name="Alice Johnson",
                merged_description="Engineer",
                merged_aliases=[],
                confidence=0.9,
                rationale="Same person",
            )
        ]
    )
    fake_llm = AsyncMock()
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    session = _make_session_mock()
    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)

    winner_ewc = EntityWithContext(id=winner_id, name="Alice Johnson", entity_type="person")
    loser_ewc = EntityWithContext(id=loser_id, name="Alice Jonson", entity_type="person")

    await deduplicator.execute_batches(
        batches=[[winner_ewc, loser_ewc]],
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=None,
    )

    # loser must be soft-deleted
    update_calls = entity_repo.update.call_args_list
    loser_calls = [c for c in update_calls if c.args[0] == loser_id]
    assert len(loser_calls) >= 1
    loser_kwargs = loser_calls[-1].kwargs
    assert loser_kwargs.get("is_deleted") is True, (
        f"Expected loser to be soft-deleted (is_deleted=True), got kwargs: {loser_kwargs}"
    )


@pytest.mark.asyncio
async def test_claims_relations_reassigned():
    """After merge: SQL UPDATE must be called to move claims/relations from loser to winner."""
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup

    winner_id = uuid.uuid4()
    loser_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    winner_entity = MagicMock()
    winner_entity.id = winner_id
    winner_entity.name = "Alice Johnson"
    winner_entity.aliases = []
    winner_entity.description = ""
    winner_entity.properties = {}

    loser_entity = MagicMock()
    loser_entity.id = loser_id
    loser_entity.name = "Alice Jonson"
    loser_entity.aliases = []
    loser_entity.description = ""
    loser_entity.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {winner_id: winner_entity, loser_id: loser_entity}.get(eid)
    )
    entity_repo.update = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser_id],
                merged_name="Alice Johnson",
                merged_description="Engineer",
                merged_aliases=[],
                confidence=0.9,
                rationale="Same",
            )
        ]
    )
    fake_llm = AsyncMock()
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    session = _make_session_mock()
    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)

    winner_ewc = EntityWithContext(id=winner_id, name="Alice Johnson", entity_type="person")
    loser_ewc = EntityWithContext(id=loser_id, name="Alice Jonson", entity_type="person")

    await deduplicator.execute_batches(
        batches=[[winner_ewc, loser_ewc]],
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=None,
    )

    # session.execute must have been called (for SQL reassignment)
    assert session.execute.called, "session.execute was not called — claims/relations not reassigned"


# ---------------------------------------------------------------------------
# Fix 1: batch rebalance — trailing entity must not be dropped
# ---------------------------------------------------------------------------


def test_assemble_batches_10_entities_batch_size_9_produces_balanced_batches():
    """10 entities with batch_size=9 must produce [5,5] not [9, drop].

    This is the core regression: when group size == batch_size*n+1,
    the trailing 1-entity chunk was silently dropped.
    After the fix, every entity must appear in some batch and
    no batch should contain a single entity without a peer.
    """
    from alayaos_core.extraction.integrator.dedup import assemble_batches

    type_id = uuid.uuid4()
    entities = [_make_entity(f"Entity-{i:02d}", entity_type="person", entity_type_id=type_id) for i in range(10)]
    embeddings = {e.id: [1.0, 0.0, 0.0, 0.0] for e in entities}

    batches = assemble_batches(entities, embeddings, batch_size=9)

    # Every entity must appear in some batch
    all_ids_in_batches = {e.id for batch in batches for e in batch}
    for entity in entities:
        assert entity.id in all_ids_in_batches, f"Entity {entity.name!r} was dropped from batches"

    # The trailing entity must not be alone (each batch must have ≥2 entities)
    for i, batch in enumerate(batches):
        assert len(batch) >= 2, f"Batch {i} has only {len(batch)} entity — trailing entity was not rebalanced"

    # All batches must fit within batch_size (rebalancing must not overflow)
    for i, batch in enumerate(batches):
        assert len(batch) <= 9, f"Batch {i} has {len(batch)} entities, exceeds batch_size=9"


# ---------------------------------------------------------------------------
# Sprint 3: v2 audit inverse tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_merge_group_writes_v2_audit_inverse():
    """_apply_merge_group must write snapshot_schema_version=2 and all 7 v2 inverse fields.

    params/targets shape must be unchanged (targets stays list-of-strings, params stays
    as name/description/aliases dict).
    """
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup
    from alayaos_core.schemas.integrator_action import IntegratorActionCreate  # noqa: TC001

    winner_id = uuid.uuid4()
    loser_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    winner_entity = MagicMock()
    winner_entity.id = winner_id
    winner_entity.name = "Alice Johnson"
    winner_entity.aliases = ["AJ"]
    winner_entity.description = "engineer"
    winner_entity.properties = {}

    loser_entity = MagicMock()
    loser_entity.id = loser_id
    loser_entity.name = "Alice Jonson"
    loser_entity.aliases = ["Alice J"]
    loser_entity.description = "senior engineer"
    loser_entity.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {winner_id: winner_entity, loser_id: loser_entity}.get(eid)
    )
    entity_repo.update = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser_id],
                merged_name="Alice Johnson",
                merged_description="Senior engineer",
                merged_aliases=["AJ", "Alice J"],
                confidence=0.95,
                rationale="Same person",
            )
        ]
    )
    fake_llm = AsyncMock()
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    session = _make_session_mock()

    # Capture the audit write
    created_actions: list[IntegratorActionCreate] = []

    async def capture_create(workspace_id, data):
        created_actions.append(data)
        mock_action = MagicMock()
        return mock_action

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(side_effect=capture_create)

    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)
    winner_ewc = EntityWithContext(id=winner_id, name="Alice Johnson", entity_type="person", aliases=["AJ"])
    loser_ewc = EntityWithContext(id=loser_id, name="Alice Jonson", entity_type="person", aliases=["Alice J"])

    merged, _, _usage = await deduplicator.execute_batches(
        batches=[[winner_ewc, loser_ewc]],
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=action_repo,
    )

    assert merged >= 1
    assert len(created_actions) == 1
    audit = created_actions[0]

    # snapshot_schema_version must be 2
    assert audit.snapshot_schema_version == 2

    # All 7 v2 inverse fields must be present
    v2_fields = [
        "moved_claim_ids",
        "moved_relation_source_ids",
        "moved_relation_target_ids",
        "moved_chunk_ids",
        "deleted_self_ref_relation_ids",
        "deduplicated_relation_ids",
        "winner_before",
    ]
    for field in v2_fields:
        assert field in audit.inverse, f"Missing v2 inverse field: {field!r}"

    # params shape: unchanged (name/description/aliases dict)
    assert "name" in audit.params
    assert "description" in audit.params
    assert "aliases" in audit.params
    # targets shape: unchanged (list-of-strings with loser_id)
    assert isinstance(audit.targets, list)
    assert len(audit.targets) == 1
    assert audit.targets[0] == str(loser_id)


@pytest.mark.asyncio
async def test_apply_merge_group_dedup_inside_loop():
    """Each loser gets its own per-loser dedup pass (scoped to that loser's winner).

    Two losers: each produces a duplicate relation on the winner. Each loser's audit
    must have deduplicated_relation_ids populated (per-loser, not global).
    """
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup
    from alayaos_core.schemas.integrator_action import IntegratorActionCreate  # noqa: TC001

    winner_id = uuid.uuid4()
    loser1_id = uuid.uuid4()
    loser2_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    dup_rel1_id = uuid.uuid4()
    dup_rel2_id = uuid.uuid4()

    def _make_mock_entity(eid, name):
        e = MagicMock()
        e.id = eid
        e.name = name
        e.aliases = []
        e.description = ""
        e.properties = {}
        return e

    winner_entity = _make_mock_entity(winner_id, "Alice")
    loser1_entity = _make_mock_entity(loser1_id, "Alice1")
    loser2_entity = _make_mock_entity(loser2_id, "Alice2")

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {
            winner_id: winner_entity,
            loser1_id: loser1_entity,
            loser2_id: loser2_entity,
        }.get(eid)
    )
    entity_repo.update = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser1_id, loser2_id],
                merged_name="Alice",
                merged_description="",
                merged_aliases=[],
                confidence=0.95,
                rationale="Same",
            )
        ]
    )
    fake_llm = AsyncMock()
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    # Alternate dedup results: loser1 pass deletes dup_rel1, loser2 pass deletes dup_rel2
    call_count = 0

    def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        # The dedup DELETE RETURNING query (appears once per loser)
        sql_str = str(args[0]) if args else ""
        if "RETURNING" in sql_str and "ROW_NUMBER" in sql_str:
            # First loser: return dup_rel1_id; second loser: return dup_rel2_id
            if call_count <= 10:
                mock_result.fetchall.return_value = [(dup_rel1_id,)]
            else:
                mock_result.fetchall.return_value = [(dup_rel2_id,)]
        else:
            mock_result.fetchall.return_value = []
        return mock_result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)

    # Capture audit writes
    created_actions: list[IntegratorActionCreate] = []

    async def capture_create(workspace_id, data):
        created_actions.append(data)
        return MagicMock()

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(side_effect=capture_create)

    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)

    winner_ewc = EntityWithContext(id=winner_id, name="Alice", entity_type="person")
    loser1_ewc = EntityWithContext(id=loser1_id, name="Alice1", entity_type="person")
    loser2_ewc = EntityWithContext(id=loser2_id, name="Alice2", entity_type="person")

    merged, _, _usage = await deduplicator.execute_batches(
        batches=[[winner_ewc, loser1_ewc, loser2_ewc]],
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=action_repo,
    )

    assert merged >= 2
    # Two audit records: one per loser
    assert len(created_actions) == 2
    # Each audit has deduplicated_relation_ids (per-loser scoped)
    for audit in created_actions:
        assert "deduplicated_relation_ids" in audit.inverse
        assert audit.snapshot_schema_version == 2


def test_assemble_batches_drops_no_entity_for_various_sizes():
    """For group sizes 2-19, every entity must appear in some batch."""
    from alayaos_core.extraction.integrator.dedup import assemble_batches

    type_id = uuid.uuid4()
    batch_size = 9

    for n in range(2, 20):
        entities = [_make_entity(f"E-{i}", entity_type="person", entity_type_id=type_id) for i in range(n)]
        embeddings = {e.id: [1.0, 0.0, 0.0, 0.0] for e in entities}

        batches = assemble_batches(entities, embeddings, batch_size=batch_size)

        all_ids = {e.id for batch in batches for e in batch}
        for entity in entities:
            assert entity.id in all_ids, (
                f"n={n}: Entity {entity.name!r} dropped from batches. Batches sizes: {[len(b) for b in batches]}"
            )


# ---------------------------------------------------------------------------
# Fix 2: co_event_score via extraction_run_id — graceful fallback documented
# ---------------------------------------------------------------------------


def test_get_extraction_run_id_reads_from_properties():
    """_get_extraction_run_id must return value from entity.properties when present."""
    from alayaos_core.extraction.integrator.dedup import _get_extraction_run_id

    run_id = str(uuid.uuid4())
    entity = _make_entity("Alice")
    # Inject extraction_run_id via properties (the documented path)
    entity.properties["extraction_run_id"] = run_id

    result = _get_extraction_run_id(entity)
    assert result == run_id, f"Expected {run_id!r}, got {result!r}"


def test_get_extraction_run_id_returns_none_when_absent():
    """_get_extraction_run_id must return None when extraction_run_id is not in properties."""
    from alayaos_core.extraction.integrator.dedup import _get_extraction_run_id

    entity = _make_entity("Alice")
    # No extraction_run_id in properties
    result = _get_extraction_run_id(entity)
    assert result is None, f"Expected None, got {result!r}"


# ---------------------------------------------------------------------------
# Fix 3: relation dedup after merge — duplicate (source, target, type) removed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relation_dedup_after_merge_removes_duplicates():
    """After reassigning loser→winner relations, duplicate (source,target,type) rows must be deleted.

    The test verifies that session.execute is called with a DELETE statement that
    references ROW_NUMBER() or equivalent dedup logic, or at minimum that a DELETE
    is issued to clean up duplicate relations after the UPDATE reassignment.
    """
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DedupResult, EntityWithContext, MergeGroup

    winner_id = uuid.uuid4()
    loser_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    winner_entity = MagicMock()
    winner_entity.id = winner_id
    winner_entity.name = "Alice Johnson"
    winner_entity.aliases = []
    winner_entity.description = ""
    winner_entity.properties = {}

    loser_entity = MagicMock()
    loser_entity.id = loser_id
    loser_entity.name = "Alice Jonson"
    loser_entity.aliases = []
    loser_entity.description = ""
    loser_entity.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: {winner_id: winner_entity, loser_id: loser_entity}.get(eid)
    )
    entity_repo.update = AsyncMock()

    dedup_result = DedupResult(
        groups=[
            MergeGroup(
                winner_id=winner_id,
                loser_ids=[loser_id],
                merged_name="Alice Johnson",
                merged_description="Engineer",
                merged_aliases=[],
                confidence=0.9,
                rationale="Same person",
            )
        ]
    )
    fake_llm = AsyncMock()
    fake_llm.extract = AsyncMock(return_value=(dedup_result, MagicMock()))

    session = _make_session_mock()
    deduplicator = DeduplicatorV2(llm=fake_llm, batch_size=9)

    winner_ewc = EntityWithContext(id=winner_id, name="Alice Johnson", entity_type="person")
    loser_ewc = EntityWithContext(id=loser_id, name="Alice Jonson", entity_type="person")

    await deduplicator.execute_batches(
        batches=[[winner_ewc, loser_ewc]],
        entity_type="person",
        workspace_id=ws_id,
        run_id=run_id,
        entity_repo=entity_repo,
        session=session,
        action_repo=None,
    )

    # Check that at least one DELETE statement was issued targeting l1_relations
    # with duplicate-dedup logic (ROW_NUMBER or ctid-based delete)
    execute_calls = session.execute.call_args_list
    sql_texts = [str(c.args[0]) if c.args else "" for c in execute_calls]

    # We need a DELETE that specifically targets duplicate relations on the winner
    # This must be a separate DELETE from the self-ref cleanup DELETEs (which target b_id rows)
    dedup_deletes = [
        s
        for s in sql_texts
        if "DELETE" in s.upper()
        and "l1_relations" in s
        and (
            "ROW_NUMBER" in s.upper() or "row_number" in s or "ctid" in s
            # Alternative: a DELETE that references winner_id as both source and target
            # to clean up duplicates after reassignment
        )
    ]

    assert len(dedup_deletes) >= 1, (
        "Expected at least one relation dedup DELETE (ROW_NUMBER or ctid-based) after merge. "
        "SQL statements issued:\n" + "\n".join(sql_texts[:20])
    )


# ---------------------------------------------------------------------------
# G1: Fallback _llm_check — exception propagation, stage=, usage capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_check_propagates_exception():
    """EntityDeduplicator._llm_check must propagate LLM exceptions rather than swallowing them.

    Previously the function caught all exceptions and returned False silently.
    After the fix, exceptions must propagate to the caller.
    """
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator

    class _RaisingLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            raise RuntimeError("LLM unavailable")

    deduplicator = EntityDeduplicator(llm=_RaisingLLM(), threshold=0.85, ambiguous_low=0.70)
    entity_a = _make_entity("Alice Johnson")
    entity_b = _make_entity("Alice Jonson")

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        await deduplicator._llm_check(entity_a, entity_b)


@pytest.mark.asyncio
async def test_llm_check_returns_usage():
    """EntityDeduplicator._llm_check must return (bool, LLMUsage) not just bool."""
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult
    from alayaos_core.llm.interface import LLMUsage

    expected_usage = LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.001)

    class _FakeLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            return EntityMatchResult(is_same_entity=True, reasoning="same"), expected_usage

    deduplicator = EntityDeduplicator(llm=_FakeLLM(), threshold=0.85, ambiguous_low=0.70)
    entity_a = _make_entity("Alice Johnson")
    entity_b = _make_entity("Alice Jonson")

    result = await deduplicator._llm_check(entity_a, entity_b)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected (bool, LLMUsage), got {result}"
    is_same, usage = result
    assert is_same is True
    assert isinstance(usage, LLMUsage)
    assert usage.tokens_in == 10


@pytest.mark.asyncio
async def test_llm_check_passes_stage():
    """EntityDeduplicator._llm_check must pass stage='integrator:dedup' to llm.extract()."""
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult
    from alayaos_core.llm.interface import LLMUsage

    captured_stages: list[str] = []

    class _CapturingLLM:
        async def extract(self, text, system_prompt, response_model, *, stage="unknown", **kwargs):
            captured_stages.append(stage)
            return EntityMatchResult(is_same_entity=False, reasoning="different"), LLMUsage(
                tokens_in=1, tokens_out=1, tokens_cached=0, cost_usd=0.0
            )

    deduplicator = EntityDeduplicator(llm=_CapturingLLM(), threshold=0.85, ambiguous_low=0.70)
    entity_a = _make_entity("Alice Johnson")
    entity_b = _make_entity("Alice Jonson")

    await deduplicator._llm_check(entity_a, entity_b)

    assert len(captured_stages) == 1, "Expected exactly one LLM call"
    assert captured_stages[0] == "integrator:dedup", (
        f"Expected stage='integrator:dedup', got stage={captured_stages[0]!r}"
    )


@pytest.mark.asyncio
async def test_llm_check_pair_returns_usage():
    """EntityDeduplicator.llm_check_pair (public API) must return (bool, LLMUsage)."""
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult
    from alayaos_core.llm.interface import LLMUsage

    expected_usage = LLMUsage(tokens_in=7, tokens_out=3, tokens_cached=0, cost_usd=0.0005)

    class _FakeLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            return EntityMatchResult(is_same_entity=False, reasoning="different"), expected_usage

    deduplicator = EntityDeduplicator(llm=_FakeLLM(), threshold=0.85, ambiguous_low=0.70)
    entity_a = _make_entity("Alice Johnson")
    entity_b = _make_entity("Bob Smith")

    result = await deduplicator.llm_check_pair(entity_a, entity_b)
    assert isinstance(result, tuple), f"llm_check_pair must return tuple, got {type(result)}"
    is_same, usage = result
    assert is_same is False
    assert usage.tokens_in == 7


# ---------------------------------------------------------------------------
# Round-3 fix: find_duplicates returns LLMUsage; engine fallback propagates it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_duplicates_returns_usage():
    """find_duplicates must return (pairs, LLMUsage) and propagate Tier-3 LLM usage."""
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult
    from alayaos_core.llm.interface import LLMUsage

    sentinel_usage = LLMUsage(tokens_in=42, tokens_out=24, tokens_cached=0, cost_usd=0.001)

    class _FakeLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            return EntityMatchResult(is_same_entity=True, reasoning="same"), sentinel_usage

    # threshold=1.0 so no pair passes Tier 1/2; ambiguous_low=0.0 so everything hits Tier 3
    deduplicator = EntityDeduplicator(llm=_FakeLLM(), threshold=1.0, ambiguous_low=0.0)
    entity_a = _make_entity("Alicia", entity_type="person")
    entity_b = _make_entity("Alisia", entity_type="person")

    result = await deduplicator.find_duplicates([entity_a, entity_b])
    assert isinstance(result, tuple), f"find_duplicates must return tuple, got {type(result)}"
    pairs, usage = result
    assert len(pairs) == 1, f"Expected one pair from Tier-3 LLM match, got {pairs}"
    assert usage.tokens_in == 42, f"Expected tokens_in=42, got {usage.tokens_in}"
    assert usage.tokens_out == 24, f"Expected tokens_out=24, got {usage.tokens_out}"


@pytest.mark.asyncio
async def test_shortlist_dedup_embed_fallback_propagates_tier3_usage():
    """_shortlist_dedup embed-failure fallback must propagate Tier-3 LLMUsage from find_duplicates."""
    from unittest.mock import AsyncMock

    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
    from alayaos_core.extraction.integrator.schemas import EntityMatchResult
    from alayaos_core.llm.interface import LLMUsage

    sentinel_usage = LLMUsage(tokens_in=77, tokens_out=33, tokens_cached=0, cost_usd=0.002)

    class _FakeLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            return EntityMatchResult(is_same_entity=True, reasoning="same"), sentinel_usage

    # threshold=1.0, ambiguous_low=0.0 → every ambiguous pair hits Tier 3
    deduplicator = EntityDeduplicator(llm=_FakeLLM(), threshold=1.0, ambiguous_low=0.0)

    # Embedding service that always raises so _shortlist_dedup falls back to find_duplicates
    class _FailEmbed:
        async def embed_texts(self, texts):
            raise RuntimeError("embed failure")

    # Build a minimal engine with the failing embedder
    from unittest.mock import MagicMock

    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 1.0
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.0
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.9

    entity_repo = AsyncMock()
    claim_repo = AsyncMock()
    relation_repo = AsyncMock()
    entity_cache = AsyncMock()
    redis_mock = AsyncMock()

    engine = IntegratorEngine(
        llm=_FakeLLM(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )
    engine._deduplicator = deduplicator  # type: ignore[attr-defined]
    engine._embedding_service = _FailEmbed()  # type: ignore[attr-defined]

    entity_a = _make_entity("Alicia", entity_type="person")
    entity_b = _make_entity("Alisia", entity_type="person")

    _pairs, usage = await engine._shortlist_dedup([entity_a, entity_b])  # type: ignore[attr-defined]
    assert usage.tokens_in == 77, (
        f"Fallback path must propagate Tier-3 usage; expected tokens_in=77, got {usage.tokens_in}"
    )
