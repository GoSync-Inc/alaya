"""Tests for extraction Pydantic schemas."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alayaos_core.extraction.integrator.schemas import (
    EntityMatchResult as IntegratorEntityMatchResult,
)
from alayaos_core.extraction.schemas import (
    EntityMatchResult,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)

# ResolverEntityMatchResult is the same class as EntityMatchResult (resolver-side alias for parametrize clarity)
ResolverEntityMatchResult = EntityMatchResult

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"

# ─── ExtractedEntity ──────────────────────────────────────────────────────────


def test_extracted_entity_valid() -> None:
    e = ExtractedEntity(name="Alice Smith", entity_type="person")
    assert e.name == "Alice Smith"
    assert e.entity_type == "person"
    assert e.confidence == 0.8
    assert e.aliases == []
    assert e.external_ids == {}
    assert e.properties == {}


def test_extracted_entity_xss_rejected() -> None:
    with pytest.raises(ValidationError, match="Script tags not allowed"):
        ExtractedEntity(name="<script>alert(1)</script>", entity_type="person")


def test_extracted_entity_xss_variants_rejected() -> None:
    """XSS variants with spaces between tag characters should be rejected."""
    with pytest.raises(ValidationError, match="Script tags not allowed"):
        ExtractedEntity(name="< script >bad</script>", entity_type="person")


def test_extracted_entity_control_chars_stripped() -> None:
    # Bell char \x07, form feed \x0c
    e = ExtractedEntity(name="Alice\x07 Smith\x0c", entity_type="person")
    assert e.name == "Alice Smith"


def test_extracted_entity_name_stripped() -> None:
    e = ExtractedEntity(name="  Alice  ", entity_type="person")
    assert e.name == "Alice"


def test_extracted_entity_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(name="X", entity_type="person", confidence=1.5)
    with pytest.raises(ValidationError):
        ExtractedEntity(name="X", entity_type="person", confidence=-0.1)


def test_extracted_entity_name_too_short() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(name="", entity_type="person")


def test_extracted_entity_aliases_max() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(name="Alice", entity_type="person", aliases=["a"] * 21)


# ─── ExtractionResult ─────────────────────────────────────────────────────────


def test_extraction_result_valid() -> None:
    r = ExtractionResult()
    assert r.entities == []
    assert r.relations == []
    assert r.claims == []


def test_extraction_result_with_entities() -> None:
    r = ExtractionResult(
        entities=[ExtractedEntity(name="Alice", entity_type="person")],
        claims=[ExtractedClaim(entity="Alice", predicate="title", value="Engineer")],
    )
    assert len(r.entities) == 1
    assert len(r.claims) == 1


def test_extraction_result_entities_max() -> None:
    entities = [ExtractedEntity(name=f"Entity {i}", entity_type="thing") for i in range(101)]
    with pytest.raises(ValidationError):
        ExtractionResult(entities=entities)


# ─── ExtractedClaim ───────────────────────────────────────────────────────────


def test_extracted_claim_valid() -> None:
    c = ExtractedClaim(entity="Alice", predicate="deadline", value="2026-04-15")
    assert c.entity == "Alice"
    assert c.value_type == "text"
    assert c.confidence == 0.8


def test_extracted_claim_source_summary_optional() -> None:
    c = ExtractedClaim(entity="Alice", predicate="title", value="PM")
    assert c.source_summary is None


# ─── ExtractedRelation ────────────────────────────────────────────────────────


def test_extracted_relation_valid() -> None:
    r = ExtractedRelation(
        source_entity="Alice",
        target_entity="Project Phoenix",
        relation_type="member_of",
    )
    assert r.confidence == 0.8


# ─── EntityMatchResult ────────────────────────────────────────────────────────


def test_entity_match_result_valid() -> None:
    r = EntityMatchResult(is_same_entity=True, reasoning="Same person with different name")
    assert r.is_same_entity is True


@pytest.mark.parametrize(
    "schema_cls",
    [
        pytest.param(ResolverEntityMatchResult, id="resolver"),
        pytest.param(IntegratorEntityMatchResult, id="integrator"),
    ],
)
def test_entity_match_result_accepts_real_llm_reasoning(
    schema_cls: type[EntityMatchResult] | type[IntegratorEntityMatchResult],
) -> None:
    """Regression: LLM-generated reasoning > 200 chars must not raise ValidationError.

    Captured from worker logs where job_write aborted with Pydantic ValidationError
    because real Sonnet output exceeded the former max_length=200 limit.
    Covers both EntityMatchResult definitions (resolver-side and integrator-side).
    """
    fixture_path = FIXTURES_DIR / "llm_responses" / "entity_match_long_reasoning.json"
    with fixture_path.open() as f:
        payload = json.load(f)

    assert len(payload["reasoning"]) > 200, "Fixture must exceed 200 chars to be a valid regression"

    result = schema_cls.model_validate(payload)
    assert result.is_same_entity is True
    assert result.reasoning == payload["reasoning"]


def test_confidence_bounds() -> None:
    """Confidence must be between 0 and 1 on all schema types."""
    with pytest.raises(ValidationError):
        ExtractedClaim(entity="X", predicate="p", value="v", confidence=1.1)
    with pytest.raises(ValidationError):
        ExtractedRelation(source_entity="X", target_entity="Y", relation_type="r", confidence=-0.5)
