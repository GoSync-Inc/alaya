"""Tests for Integrator schemas."""

import uuid

from alayaos_core.extraction.integrator.schemas import (
    DuplicatePair,
    EnrichmentAction,
    EnrichmentResult,
    EntityWithContext,
    IntegratorRunResult,
)


def test_entity_with_context_defaults():
    e = EntityWithContext(
        id=uuid.uuid4(),
        name="Alice",
        entity_type="person",
    )
    assert e.aliases == []
    assert e.properties == {}
    assert e.claims == []
    assert e.relations == []


def test_duplicate_pair_fields():
    a = uuid.uuid4()
    b = uuid.uuid4()
    dp = DuplicatePair(
        entity_a_id=a,
        entity_b_id=b,
        entity_a_name="Alice",
        entity_b_name="Alisa",
        score=0.9,
        method="fuzzy",
    )
    assert dp.method == "fuzzy"
    assert dp.score == 0.9


def test_enrichment_action_defaults():
    ea = EnrichmentAction(action="add_relation", entity_id=uuid.uuid4())
    assert ea.details == {}


def test_enrichment_result_defaults():
    er = EnrichmentResult()
    assert er.actions == []


def test_integrator_run_result_defaults():
    r = IntegratorRunResult(status="completed")
    assert r.entities_scanned == 0
    assert r.tokens_used == 0
    assert r.cost_usd == 0.0
    assert r.reason is None


def test_integrator_run_result_skipped():
    r = IntegratorRunResult(status="skipped", reason="locked")
    assert r.reason == "locked"
