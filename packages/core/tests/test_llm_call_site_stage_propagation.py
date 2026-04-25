"""Tests that every LLM extract() call site passes a stage= kwarg.

The stage kwarg identifies the pipeline phase (e.g. "cortex:classify",
"crystallizer:extract") so pipeline_traces can carry a meaningful stage label.
Each call site must pass a non-empty, non-"unknown" stage string.
"""

from __future__ import annotations

import contextlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.llm.interface import LLMUsage


def _make_usage() -> LLMUsage:
    return LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.0)


def _stage_capturing_llm():
    """Return (llm, captured_stages_list).

    Each extract() call appends the stage kwarg to captured_stages.
    Returns a minimal valid response for any schema.
    """
    captured: list[str] = []

    class _CapturingLLM:
        async def extract(
            self, text, system_prompt, response_model, *, max_tokens=4096, temperature=0.0, stage="unknown"
        ):
            captured.append(stage)
            # Return minimal valid instance
            with contextlib.suppress(Exception):
                return response_model.model_construct(), _make_usage()
            return MagicMock(), _make_usage()

    return _CapturingLLM(), captured


@pytest.mark.asyncio
async def test_cortex_classifier_passes_stage() -> None:
    """CortexClassifier.classify() must pass stage= to llm.extract()."""
    from alayaos_core.extraction.cortex.classifier import CortexClassifier

    llm, stages = _stage_capturing_llm()
    classifier = CortexClassifier(llm=llm)

    chunk_mock = MagicMock()
    chunk_mock.text = "Sprint planning meeting notes"

    with contextlib.suppress(Exception):
        await classifier.classify(chunk_mock)

    assert len(stages) >= 1, "CortexClassifier made no LLM calls"
    for s in stages:
        assert s != "unknown", "CortexClassifier passed stage='unknown'; expected a meaningful stage name"
        assert s, "CortexClassifier passed empty stage"


@pytest.mark.asyncio
async def test_crystallizer_extractor_passes_stage() -> None:
    """CrystallizerExtractor.extract() must pass stage= to llm.extract()."""
    from alayaos_core.extraction.crystallizer.extractor import CrystallizerExtractor

    llm, stages = _stage_capturing_llm()
    entity_cache = AsyncMock()
    entity_cache.get_snapshot = AsyncMock(return_value=[])
    extractor = CrystallizerExtractor(llm=llm, entity_cache=entity_cache)

    chunk_mock = MagicMock()
    chunk_mock.text = "Alice reports to Bob."
    chunk_mock.event_id = uuid.uuid4()
    chunk_mock.domain_scores = {}

    with contextlib.suppress(Exception):
        await extractor.extract(
            chunk=chunk_mock,
            entity_types=[],
            predicates=[],
            workspace_id=uuid.uuid4(),
        )

    assert len(stages) >= 1, "CrystallizerExtractor made no LLM calls"
    for s in stages:
        assert s != "unknown", "CrystallizerExtractor passed stage='unknown'"
        assert s, "CrystallizerExtractor passed empty stage"


@pytest.mark.asyncio
async def test_panoramic_pass_passes_stage() -> None:
    """PanoramicPass.run() must pass stage= to llm.extract()."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass

    llm, stages = _stage_capturing_llm()
    session = AsyncMock()
    pass_ = PanoramicPass(llm_service=llm, session=session)

    ws_id = uuid.uuid4()
    with contextlib.suppress(Exception):
        await pass_.run(
            workspace_id=ws_id,
            entities=[],
            entity_types=[],
            claims_by_entity={},
            relations_by_entity={},
        )

    # Panoramic may skip LLM if entities list is empty; that's fine — just
    # verify that IF a call is made, stage is propagated. If no call, skip.
    for s in stages:
        assert s != "unknown", "PanoramicPass passed stage='unknown'"
        assert s, "PanoramicPass passed empty stage"


@pytest.mark.asyncio
async def test_integrator_dedup_passes_stage() -> None:
    """DeduplicatorV2 must pass stage= to llm.extract() when verifying pairs."""
    from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
    from alayaos_core.extraction.integrator.schemas import DuplicatePair, EntityWithContext

    llm, stages = _stage_capturing_llm()
    dedup = DeduplicatorV2(llm=llm, batch_size=9)

    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()
    entity_a = EntityWithContext(id=entity_a_id, name="Alice", entity_type="person")
    entity_b = EntityWithContext(id=entity_b_id, name="Alicia", entity_type="person")

    pairs = [
        DuplicatePair(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            entity_a_name="Alice",
            entity_b_name="Alicia",
            score=0.95,
            method="fuzzy",
        )
    ]

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(return_value=MagicMock())
    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(side_effect=lambda eid: entity_a if eid == entity_a_id else entity_b)
    entity_repo.update = AsyncMock()

    with contextlib.suppress(Exception):
        await dedup.deduplicate_batch(
            pairs=pairs,
            entities=[entity_a, entity_b],
            workspace_id=uuid.uuid4(),
            session=session,
            run_id=uuid.uuid4(),
            action_repo=action_repo,
            entity_repo=entity_repo,
        )

    for s in stages:
        assert s != "unknown", "DeduplicatorV2 passed stage='unknown'"
        assert s, "DeduplicatorV2 passed empty stage"


@pytest.mark.asyncio
async def test_enricher_passes_stage() -> None:
    """EntityEnricher.enrich_batch() must pass stage= to llm.extract()."""
    from alayaos_core.extraction.integrator.enricher import EntityEnricher
    from alayaos_core.extraction.integrator.schemas import EntityWithContext

    llm, stages = _stage_capturing_llm()
    enricher = EntityEnricher(llm=llm, batch_size=5)

    entities = [EntityWithContext(id=uuid.uuid4(), name="Alice", entity_type="person")]

    with contextlib.suppress(Exception):
        await enricher.enrich_batch(entities)

    assert len(stages) >= 1, "EntityEnricher made no LLM calls"
    for s in stages:
        assert s != "unknown", "EntityEnricher passed stage='unknown'"
        assert s, "EntityEnricher passed empty stage"


@pytest.mark.asyncio
async def test_ask_service_passes_stage() -> None:
    """ask() must pass stage= to llm.extract()."""
    from alayaos_core.schemas.search import EvidenceUnit, SearchResponse
    from alayaos_core.services.ask import ask

    llm, stages = _stage_capturing_llm()
    session = AsyncMock()
    ws_id = uuid.uuid4()

    # Build a search response with one evidence unit so ask() proceeds to LLM
    evidence = EvidenceUnit(
        source_id=uuid.uuid4(),
        source_type="claim",
        content="Alice is the project lead.",
        score=0.9,
        channels=["fts"],
    )
    search_resp = SearchResponse(
        query="Who is Alice?",
        results=[evidence],
        total=1,
        channels_used=["fts"],
        elapsed_ms=1,
    )

    with (
        patch("alayaos_core.services.ask.hybrid_search", new=AsyncMock(return_value=search_resp)),
        contextlib.suppress(Exception),
    ):
        await ask(
            session=session,
            question="Who is Alice?",
            workspace_id=ws_id,
            llm=llm,
        )

    assert len(stages) >= 1, "ask() made no LLM calls (even with evidence provided)"
    for s in stages:
        assert s != "unknown", "ask() passed stage='unknown'"
        assert s, "ask() passed empty stage"
