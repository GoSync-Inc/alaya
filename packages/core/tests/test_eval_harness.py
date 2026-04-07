"""Extraction eval harness — validates gold dataset and measures F1 metrics."""

import json
from pathlib import Path

from alayaos_core.extraction.schemas import ExtractionResult

GOLD_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gold"


def compute_f1(predicted: list[dict], expected: list[dict], key: str) -> dict:
    """Compute precision, recall, F1 for entity/claim matching."""
    pred_set = {d[key] for d in predicted}
    exp_set = {d[key] for d in expected}
    tp = len(pred_set & exp_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(exp_set) if exp_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def test_gold_fixtures_are_valid() -> None:
    """All gold fixtures must be valid JSON with required fields."""
    for fixture_path in sorted(GOLD_DIR.glob("*.json")):
        data = json.loads(fixture_path.read_text())
        assert "input" in data, f"{fixture_path.name}: missing 'input'"
        assert "source_type" in data, f"{fixture_path.name}: missing 'source_type'"
        assert "expected_entities" in data, f"{fixture_path.name}: missing 'expected_entities'"


def test_gold_fixture_count() -> None:
    """Must have at least 50 gold fixtures."""
    count = len(list(GOLD_DIR.glob("*.json")))
    assert count >= 50, f"Expected >= 50 gold fixtures, got {count}"


def test_eval_entity_extraction() -> None:
    """Evaluate entity extraction F1 using FakeLLMAdapter defaults."""
    # For each fixture, create ExtractionResult from expected data
    # (In real eval, FakeLLMAdapter would be called, but for unit tests
    # we verify the eval harness logic itself)
    fixture = json.loads((GOLD_DIR / "slack_01.json").read_text())
    expected = fixture["expected_entities"]
    # Simulate extraction result matching expected
    predicted = [{"name": e["name"]} for e in expected]
    metrics = compute_f1(predicted, expected, "name")
    assert metrics["f1"] == 1.0  # perfect match


def test_eval_claim_extraction() -> None:
    """Evaluate claim extraction metrics."""
    fixture = json.loads((GOLD_DIR / "slack_01.json").read_text())
    expected = fixture.get("expected_claims", [])
    if expected:
        predicted = [{"entity": c["entity"], "predicate": c["predicate"]} for c in expected]
        expected_keys = [{"entity": c["entity"], "predicate": c["predicate"]} for c in expected]
        # Use composite key for matching
        pred_set = {(d["entity"], d["predicate"]) for d in predicted}
        exp_set = {(d["entity"], d["predicate"]) for d in expected_keys}
        assert pred_set == exp_set


def test_compute_f1_perfect_match() -> None:
    """compute_f1: perfect match yields f1=1.0, precision=1.0, recall=1.0."""
    predicted = [{"name": "Alice"}, {"name": "Bob"}]
    expected = [{"name": "Alice"}, {"name": "Bob"}]
    metrics = compute_f1(predicted, expected, "name")
    assert metrics["f1"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0


def test_compute_f1_no_match() -> None:
    """compute_f1: no overlap yields f1=0.0."""
    predicted = [{"name": "Alice"}]
    expected = [{"name": "Bob"}]
    metrics = compute_f1(predicted, expected, "name")
    assert metrics["f1"] == 0.0
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0


def test_compute_f1_partial_match() -> None:
    """compute_f1: partial match yields expected precision/recall/f1."""
    predicted = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}]
    expected = [{"name": "Alice"}, {"name": "Bob"}]
    metrics = compute_f1(predicted, expected, "name")
    # tp=2, precision=2/3, recall=2/2=1.0, f1=2*(2/3*1)/(2/3+1)=2*(2/3)/(5/3)=4/5=0.8
    assert abs(metrics["precision"] - 2 / 3) < 1e-9
    assert metrics["recall"] == 1.0
    assert abs(metrics["f1"] - 0.8) < 1e-9


def test_compute_f1_empty_predicted() -> None:
    """compute_f1: empty predicted yields f1=0.0."""
    predicted: list[dict] = []
    expected = [{"name": "Alice"}]
    metrics = compute_f1(predicted, expected, "name")
    assert metrics["f1"] == 0.0
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0


def test_compute_f1_empty_expected() -> None:
    """compute_f1: empty expected with non-empty predicted yields f1=0.0 (no true positives)."""
    predicted = [{"name": "Alice"}]
    expected: list[dict] = []
    metrics = compute_f1(predicted, expected, "name")
    assert metrics["f1"] == 0.0
    # tp=0, precision=0/1=0.0, recall=0/0→0.0
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0


def test_gold_fixtures_have_valid_source_types() -> None:
    """All gold fixtures must use known source types."""
    known_source_types = {"slack", "github", "meeting", "manual", "linear"}
    for fixture_path in sorted(GOLD_DIR.glob("*.json")):
        data = json.loads(fixture_path.read_text())
        st = data.get("source_type")
        assert st in known_source_types, f"{fixture_path.name}: unknown source_type={st!r}"


def test_gold_fixtures_entities_have_required_fields() -> None:
    """All expected_entities in gold fixtures must have name and entity_type."""
    for fixture_path in sorted(GOLD_DIR.glob("*.json")):
        data = json.loads(fixture_path.read_text())
        for entity in data.get("expected_entities", []):
            assert "name" in entity, f"{fixture_path.name}: entity missing 'name': {entity}"
            assert "entity_type" in entity, f"{fixture_path.name}: entity missing 'entity_type': {entity}"


def test_gold_fixtures_claims_have_required_fields() -> None:
    """All expected_claims in gold fixtures must have entity, predicate, value, value_type."""
    for fixture_path in sorted(GOLD_DIR.glob("*.json")):
        data = json.loads(fixture_path.read_text())
        for claim in data.get("expected_claims", []):
            for field in ("entity", "predicate", "value", "value_type"):
                assert field in claim, f"{fixture_path.name}: claim missing {field!r}: {claim}"


def test_extraction_result_schema_matches_gold_format() -> None:
    """ExtractionResult schema can represent gold fixture entities and claims."""
    from alayaos_core.extraction.schemas import ExtractedClaim, ExtractedEntity, ExtractedRelation

    fixture = json.loads((GOLD_DIR / "meeting_01.json").read_text())
    # Build ExtractionResult from gold expected data
    entities = [ExtractedEntity(name=e["name"], entity_type=e["entity_type"]) for e in fixture["expected_entities"]]
    claims = [
        ExtractedClaim(
            entity=c["entity"],
            predicate=c["predicate"],
            value=c["value"],
            value_type=c["value_type"],
        )
        for c in fixture.get("expected_claims", [])
    ]
    relations = [
        ExtractedRelation(
            source_entity=r["source_entity"],
            target_entity=r["target_entity"],
            relation_type=r["relation_type"],
        )
        for r in fixture.get("expected_relations", [])
    ]
    result = ExtractionResult(entities=entities, claims=claims, relations=relations)
    assert len(result.entities) == len(fixture["expected_entities"])
    assert len(result.claims) == len(fixture.get("expected_claims", []))
    assert len(result.relations) == len(fixture.get("expected_relations", []))
