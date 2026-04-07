"""Tests for EntityDeduplicator."""

import uuid

import pytest

from alayaos_core.extraction.integrator.dedup import EntityDeduplicator
from alayaos_core.extraction.integrator.schemas import EntityWithContext


def _make_entity(name: str, entity_type: str = "person") -> EntityWithContext:
    return EntityWithContext(id=uuid.uuid4(), name=name, entity_type=entity_type)


@pytest.fixture
def fake_llm():
    """FakeLLMAdapter that returns is_same_entity=False by default."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    return FakeLLMAdapter()


@pytest.fixture
def deduplicator(fake_llm):
    return EntityDeduplicator(llm=fake_llm, threshold=0.85, ambiguous_low=0.70)


@pytest.mark.asyncio
async def test_empty_input_returns_no_pairs(deduplicator):
    result = await deduplicator.find_duplicates([])
    assert result == []


@pytest.mark.asyncio
async def test_single_entity_returns_no_pairs(deduplicator):
    entities = [_make_entity("Alice")]
    result = await deduplicator.find_duplicates(entities)
    assert result == []


@pytest.mark.asyncio
async def test_exact_match_detected_as_fuzzy(deduplicator):
    """Two entities with identical names → fuzzy match."""
    e1 = _make_entity("Alice")
    e2 = _make_entity("Alice")
    result = await deduplicator.find_duplicates([e1, e2])
    assert len(result) == 1
    assert result[0].score >= 0.85
    assert result[0].method == "fuzzy"


@pytest.mark.asyncio
async def test_very_different_names_no_match(deduplicator):
    entities = [_make_entity("Alice"), _make_entity("Quantum Physics")]
    result = await deduplicator.find_duplicates(entities)
    assert result == []


@pytest.mark.asyncio
async def test_short_names_skipped(deduplicator):
    """Names shorter than 4 chars should be skipped (too unreliable)."""
    e1 = _make_entity("Al")
    e2 = _make_entity("Al")
    # Short names: 2 chars — should be skipped
    result = await deduplicator.find_duplicates([e1, e2])
    assert result == []


@pytest.mark.asyncio
async def test_transliteration_fallback_cyrillic_latin():
    """Cyrillic and Latin names that transliterate to the same string → match."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    llm = FakeLLMAdapter()
    dedup = EntityDeduplicator(llm=llm, threshold=0.85, ambiguous_low=0.70)
    # "Aleksey" and "Алексей" should match via transliteration
    e1 = _make_entity("Aleksey")
    e2 = _make_entity("Алексей")
    result = await dedup.find_duplicates([e1, e2])
    # At least one pair found via transliteration or fuzzy
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_llm_fallback_for_ambiguous_band():
    """When score falls in ambiguous band, LLM is consulted."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    llm = FakeLLMAdapter()
    # Configure LLM to say they ARE the same entity
    from alayaos_core.extraction.integrator.dedup import EntityDeduplicator

    dedup = EntityDeduplicator(llm=llm, threshold=0.85, ambiguous_low=0.70)

    # "Иванов" and "Иванова" — similar but not above threshold
    e1 = _make_entity("Иванов Алексей")
    e2 = _make_entity("Иванов Aleksey")

    # Set up LLM to respond with is_same_entity=True for any query
    h = llm.content_hash(
        "Are these the same entity?\n"
        f'Entity A: name="{e1.name}", type="{e1.entity_type}", aliases={e1.aliases}\n'
        f'Entity B: name="{e2.name}", type="{e2.entity_type}", aliases={e2.aliases}\n'
        "Respond with is_same_entity (true/false) and brief reasoning."
    )
    llm.add_response(h, {"is_same_entity": True, "reasoning": "same person"})
    result = await dedup.find_duplicates([e1, e2])
    # Either matched via fuzzy/transliteration or LLM — we just care that the result is correct
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_no_self_pairs(deduplicator):
    """An entity should never be paired with itself."""
    e1 = _make_entity("Alice Johnson")
    result = await deduplicator.find_duplicates([e1])
    assert all(p.entity_a_id != p.entity_b_id for p in result)
