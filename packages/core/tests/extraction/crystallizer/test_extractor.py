"""Tests for CrystallizerExtractor, CrystallizerVerifier, and apply_confidence_tiers."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.crystallizer.extractor import CrystallizerExtractor, apply_confidence_tiers
from alayaos_core.extraction.crystallizer.verifier import CrystallizerVerifier
from alayaos_core.extraction.schemas import ExtractedEntity, ExtractionResult
from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.services.entity_cache import EntityCacheService

# ─── Helpers ─────────────────────────────────────────────────────────────────


def make_chunk(
    text: str = "Alice and Bob met to discuss the Gamma project status.",
    domain_scores: dict | None = None,
    primary_domain: str = "people",
) -> MagicMock:
    chunk = MagicMock()
    chunk.id = uuid.uuid4()
    chunk.text = text
    chunk.domain_scores = domain_scores or {"people": 0.8, "project": 0.4}
    chunk.primary_domain = primary_domain
    return chunk


def make_cache_with_entities(entities: list[dict]) -> EntityCacheService:
    """Build EntityCacheService mock that returns pre-set entities."""
    svc = MagicMock(spec=EntityCacheService)
    svc.get_snapshot = AsyncMock(return_value=entities)
    return svc


ENTITY_TYPES = [
    {"slug": "person", "name": "Person", "description": "A person"},
    {"slug": "project", "name": "Project", "description": "A project"},
]
PREDICATES = [{"slug": "member_of", "name": "Member Of"}]


# ─── Entity snapshot injection ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_snapshot_injected_into_prompt() -> None:
    """Entity cache snapshot appears in the system prompt."""
    llm = FakeLLMAdapter()
    cache = make_cache_with_entities([{"name": "Alice", "entity_type": "person", "aliases": []}])
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)
    chunk = make_chunk()
    ws = uuid.uuid4()

    captured_prompts = []
    original_extract = llm.extract

    async def capture_extract(text, system_prompt, model, **kwargs):
        captured_prompts.append(system_prompt)
        return await original_extract(text, system_prompt, model, **kwargs)

    llm.extract = capture_extract
    await extractor.extract(chunk, ENTITY_TYPES, PREDICATES, ws)

    assert len(captured_prompts) == 1
    assert "Alice" in captured_prompts[0]
    assert "Known Entities" in captured_prompts[0]


@pytest.mark.asyncio
async def test_no_snapshot_section_when_cache_empty() -> None:
    """When cache returns empty list, no 'Known Entities' section in prompt."""
    llm = FakeLLMAdapter()
    cache = make_cache_with_entities([])
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)
    chunk = make_chunk()
    ws = uuid.uuid4()

    captured_prompts = []
    original_extract = llm.extract

    async def capture_extract(text, system_prompt, model, **kwargs):
        captured_prompts.append(system_prompt)
        return await original_extract(text, system_prompt, model, **kwargs)

    llm.extract = capture_extract
    await extractor.extract(chunk, ENTITY_TYPES, PREDICATES, ws)

    assert "Known Entities" not in captured_prompts[0]


# ─── apply_confidence_tiers ────────────────────────────────────────────────────


def test_apply_confidence_tiers_high() -> None:
    entity = ExtractedEntity(name="Alice", entity_type="person", confidence=0.95)
    result = ExtractionResult(entities=[entity])
    apply_confidence_tiers(result, high=0.9, low=0.5)
    assert result.entities[0].tier == "high"


def test_apply_confidence_tiers_medium() -> None:
    entity = ExtractedEntity(name="Beta", entity_type="project", confidence=0.7)
    result = ExtractionResult(entities=[entity])
    apply_confidence_tiers(result, high=0.9, low=0.5)
    assert result.entities[0].tier == "medium"


def test_apply_confidence_tiers_low() -> None:
    entity = ExtractedEntity(name="Gamma", entity_type="project", confidence=0.3)
    result = ExtractionResult(entities=[entity])
    apply_confidence_tiers(result, high=0.9, low=0.5)
    assert result.entities[0].tier == "low"


def test_apply_confidence_tiers_boundary_high() -> None:
    """Exactly at high threshold → high."""
    entity = ExtractedEntity(name="Delta", entity_type="team", confidence=0.9)
    result = ExtractionResult(entities=[entity])
    apply_confidence_tiers(result, high=0.9, low=0.5)
    assert result.entities[0].tier == "high"


def test_apply_confidence_tiers_boundary_low() -> None:
    """Exactly at low threshold → medium (not low)."""
    entity = ExtractedEntity(name="Epsilon", entity_type="team", confidence=0.5)
    result = ExtractionResult(entities=[entity])
    apply_confidence_tiers(result, high=0.9, low=0.5)
    assert result.entities[0].tier == "medium"


def test_apply_confidence_tiers_multiple_entities() -> None:
    entities = [
        ExtractedEntity(name="Alice", entity_type="person", confidence=0.95),
        ExtractedEntity(name="Beta", entity_type="project", confidence=0.6),
        ExtractedEntity(name="Risk A", entity_type="risk", confidence=0.2),
    ]
    result = ExtractionResult(entities=entities)
    apply_confidence_tiers(result)
    assert result.entities[0].tier == "high"
    assert result.entities[1].tier == "medium"
    assert result.entities[2].tier == "low"


# ─── Domain-to-type mapping ────────────────────────────────────────────────────


def test_relevant_types_people_domain() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)
    types = extractor._relevant_types({"people": 0.8, "smalltalk": 0.1})
    assert "person" in types
    assert "team" in types


def test_relevant_types_below_threshold_returns_none() -> None:
    """Scores below 0.2 → no types selected → returns None (all types)."""
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)
    types = extractor._relevant_types({"people": 0.1, "engineering": 0.05})
    assert types is None


def test_relevant_types_multiple_domains() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)
    types = extractor._relevant_types({"project": 0.8, "people": 0.5})
    assert "project" in types
    assert "person" in types
    assert "team" in types


# ─── Validation: reject garbage entities ──────────────────────────────────────


def test_validate_rejects_name_over_12_words() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)

    long_name = " ".join(["word"] * 13)
    entity = ExtractedEntity(name=long_name, entity_type="project")
    result = ExtractionResult(entities=[entity])
    validated = extractor._validate(result)
    assert len(validated.entities) == 0


def test_validate_accepts_name_at_12_words() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)

    twelve_word_name = " ".join(["word"] * 12)
    entity = ExtractedEntity(name=twelve_word_name, entity_type="project")
    result = ExtractionResult(entities=[entity])
    validated = extractor._validate(result)
    assert len(validated.entities) == 1


def test_validate_rejects_question_entities() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)

    entity = ExtractedEntity(name="What is the status?", entity_type="unknown")
    result = ExtractionResult(entities=[entity])
    validated = extractor._validate(result)
    assert len(validated.entities) == 0


def test_validate_keeps_valid_entities() -> None:
    llm = FakeLLMAdapter()
    cache = EntityCacheService(redis=None)
    extractor = CrystallizerExtractor(llm=llm, entity_cache=cache)

    valid = ExtractedEntity(name="Alpha Project", entity_type="project")
    invalid_q = ExtractedEntity(name="Is this done?", entity_type="unknown")
    invalid_long = ExtractedEntity(name=" ".join(["x"] * 13), entity_type="project")
    result = ExtractionResult(entities=[valid, invalid_q, invalid_long])
    validated = extractor._validate(result)
    assert len(validated.entities) == 1
    assert validated.entities[0].name == "Alpha Project"


# ─── CrystallizerVerifier ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verifier_returns_changed_true_when_result_differs() -> None:
    llm = FakeLLMAdapter()

    # Register a non-default response for the verify call
    initial = ExtractionResult()
    user_text = (
        f"You previously extracted:\n{initial.model_dump_json(indent=2)}\n\n"
        "Review the original text and correct any:\n"
        "- False entities (not actually mentioned)\n"
        "- Wrong entity types\n"
        "- Missing relations\n"
        "- Incorrect confidence scores\n\n"
        "Return the corrected extraction."
    )
    h = FakeLLMAdapter.content_hash(user_text)
    # Register a result with an entity — different from initial (empty)
    llm.add_response(
        h,
        {
            "entities": [{"name": "Alice", "entity_type": "person", "confidence": 0.9}],
            "relations": [],
            "claims": [],
        },
    )

    verifier = CrystallizerVerifier(llm=llm)
    verified, changed, _usage = await verifier.verify(
        chunk_text="Alice leads the project.",
        system_prompt="system prompt",
        initial_result=initial,
    )
    assert changed is True
    assert len(verified.entities) == 1


@pytest.mark.asyncio
async def test_verifier_returns_changed_false_when_result_matches() -> None:
    """FakeLLMAdapter default returns empty ExtractionResult — same as initial."""
    llm = FakeLLMAdapter()
    initial = ExtractionResult()  # empty — matches FakeLLMAdapter default

    verifier = CrystallizerVerifier(llm=llm)
    _verified, changed, _usage = await verifier.verify(
        chunk_text="Some text.",
        system_prompt="system prompt",
        initial_result=initial,
    )
    assert changed is False


@pytest.mark.asyncio
async def test_verifier_uses_same_system_prompt() -> None:
    """Verifier passes the same system_prompt as in extract — enables prompt cache hit."""
    llm = FakeLLMAdapter()
    captured = []
    original = llm.extract

    async def capture(text, system_prompt, model, **kwargs):
        captured.append(system_prompt)
        return await original(text, system_prompt, model, **kwargs)

    llm.extract = capture

    verifier = CrystallizerVerifier(llm=llm)
    await verifier.verify(
        chunk_text="text",
        system_prompt="MY SYSTEM PROMPT",
        initial_result=ExtractionResult(),
    )
    assert captured[0] == "MY SYSTEM PROMPT"
