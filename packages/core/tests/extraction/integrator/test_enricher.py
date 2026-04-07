"""Tests for EntityEnricher."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from alayaos_core.extraction.integrator.enricher import EntityEnricher
from alayaos_core.extraction.integrator.schemas import (
    EnrichmentAction,
    EnrichmentResult,
    EntityWithContext,
)


def _make_entity(name: str, entity_type: str = "person", **kwargs) -> EntityWithContext:
    return EntityWithContext(id=uuid.uuid4(), name=name, entity_type=entity_type, **kwargs)


@pytest.fixture
def fake_llm():
    from alayaos_core.llm.fake import FakeLLMAdapter

    return FakeLLMAdapter()


@pytest.fixture
def enricher(fake_llm):
    return EntityEnricher(llm=fake_llm, batch_size=5)


@pytest.mark.asyncio
async def test_empty_batch_returns_empty_result(enricher):
    result = await enricher.enrich_batch([])
    assert isinstance(result, EnrichmentResult)
    assert result.actions == []


@pytest.mark.asyncio
async def test_enrich_batch_returns_enrichment_result(enricher):
    entities = [_make_entity("Alice"), _make_entity("ProjectX", entity_type="project")]
    result = await enricher.enrich_batch(entities)
    assert isinstance(result, EnrichmentResult)
    assert isinstance(result.actions, list)


@pytest.mark.asyncio
async def test_actions_are_enrichment_action_instances(enricher):
    """Each action in result must be an EnrichmentAction instance."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    llm = FakeLLMAdapter()
    enricher_with_action = EntityEnricher(llm=llm, batch_size=10)

    entity_id = uuid.uuid4()
    # Add a mock response that returns an add_relation action
    prompt_entities = [_make_entity("Alice"), _make_entity("ProjectX", entity_type="project")]
    # Build the prompt to get the hash
    import json

    from alayaos_core.extraction.integrator.enricher import _build_enrichment_prompt

    prompt = _build_enrichment_prompt(prompt_entities)
    h = llm.content_hash(prompt)
    llm.add_response(
        h,
        {
            "actions": [
                {
                    "action": "add_relation",
                    "entity_id": str(entity_id),
                    "details": {"target": "ProjectX", "relation": "member_of"},
                }
            ]
        },
    )
    result = await enricher_with_action.enrich_batch(prompt_entities)
    assert isinstance(result, EnrichmentResult)
    for action in result.actions:
        assert isinstance(action, EnrichmentAction)


@pytest.mark.asyncio
async def test_batching_splits_large_list():
    """With batch_size=2, a list of 5 entities triggers 3 LLM calls."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    call_count = 0
    original_extract = FakeLLMAdapter.extract

    class CountingLLM(FakeLLMAdapter):
        async def extract(self, text, system_prompt, response_model, **kwargs):
            nonlocal call_count
            call_count += 1
            return await super().extract(text, system_prompt, response_model, **kwargs)

    llm = CountingLLM()
    enricher = EntityEnricher(llm=llm, batch_size=2)
    entities = [_make_entity(f"Entity{i}") for i in range(5)]
    await enricher.enrich_batch(entities)
    # 5 entities with batch_size=2 → ceil(5/2)=3 calls
    assert call_count == 3


@pytest.mark.asyncio
async def test_noise_entities_flagged():
    """remove_noise action should be valid in response."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    llm = FakeLLMAdapter()
    enricher = EntityEnricher(llm=llm, batch_size=5)

    entity = _make_entity("some_random_hash_abc123")
    from alayaos_core.extraction.integrator.enricher import _build_enrichment_prompt

    prompt = _build_enrichment_prompt([entity])
    h = llm.content_hash(prompt)
    llm.add_response(
        h,
        {
            "actions": [
                {
                    "action": "remove_noise",
                    "entity_id": str(entity.id),
                    "details": {"reason": "looks like a hash, not an entity"},
                }
            ]
        },
    )

    result = await enricher.enrich_batch([entity])
    assert any(a.action == "remove_noise" for a in result.actions)


@pytest.mark.asyncio
async def test_relations_suggested():
    """add_relation action should be valid in response."""
    from alayaos_core.llm.fake import FakeLLMAdapter

    llm = FakeLLMAdapter()
    enricher = EntityEnricher(llm=llm, batch_size=5)
    task_entity = _make_entity("Deploy backend", entity_type="task")
    project_entity = _make_entity("ProjectX", entity_type="project")

    from alayaos_core.extraction.integrator.enricher import _build_enrichment_prompt

    prompt = _build_enrichment_prompt([task_entity, project_entity])
    h = llm.content_hash(prompt)
    llm.add_response(
        h,
        {
            "actions": [
                {
                    "action": "add_relation",
                    "entity_id": str(task_entity.id),
                    "details": {"target_entity_id": str(project_entity.id), "relation_type": "part_of"},
                }
            ]
        },
    )
    result = await enricher.enrich_batch([task_entity, project_entity])
    assert any(a.action == "add_relation" for a in result.actions)
