"""Tests for PanoramicPass — knowledge graph triage pass."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.integrator.schemas import EntityWithContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    name: str,
    entity_type: str = "project",
    entity_id: uuid.UUID | None = None,
) -> EntityWithContext:
    return EntityWithContext(
        id=entity_id or uuid.uuid4(),
        name=name,
        entity_type=entity_type,
        aliases=[],
        properties={},
        claims=[],
        relations=[],
    )


def _make_fake_llm_with_actions(actions: list[dict]):
    """Return a fake LLM adapter that always responds with the given actions list."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.llm.interface import LLMUsage

    class _FixedPanoramicLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            if response_model is PanoramicResult:
                result = PanoramicResult.model_validate({"actions": actions})
            else:
                result = response_model.model_validate({})
            usage = LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.0)
            return result, usage

    return _FixedPanoramicLLM()


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Test: basic pass returns PanoramicResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_panoramic_pass_emits_actions():
    """PanoramicPass.run() returns a PanoramicResult with actions from LLM."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    entity_id = uuid.uuid4()
    actions = [
        {
            "action": "remove_noise",
            "entity_id": str(entity_id),
            "params": {"reason": "garbage"},
            "confidence": 0.9,
            "rationale": "This is a hex-ID artifact",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    entity = _make_entity("some-project", entity_id=entity_id)

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) >= 1


# ---------------------------------------------------------------------------
# Test: hex-ID entities get garbage_hint=true in the prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hex_id_garbage_hint():
    """Entities with hex-ID names (^[0-9a-f]{16,}$) get garbage_hint=true in the entity table."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass

    hex_name = "a1b2c3d4e5f6a7b8"  # 16 hex chars — typical Slack/system artifact
    entity = _make_entity(hex_name)

    prompt_texts: list[str] = []

    class CapturingLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            prompt_texts.append(text)
            from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
            from alayaos_core.llm.interface import LLMUsage

            result = PanoramicResult(actions=[])
            usage = LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.0)
            return result, usage

    session = _make_session()

    panoramic = PanoramicPass(llm_service=CapturingLLM(), session=session)
    await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert len(prompt_texts) >= 1
    # The prompt must mention garbage_hint for this entity
    combined_prompt = "\n".join(prompt_texts)
    assert "garbage_hint" in combined_prompt


# ---------------------------------------------------------------------------
# Test: Slack-handle entities get garbage_hint=true
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slack_handle_garbage_hint():
    """Entities with Slack handle names (^U[A-Z0-9]{8,}$) get garbage_hint=true."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass

    slack_name = "UABCDEFGHI"  # Slack user ID pattern
    entity = _make_entity(slack_name)

    prompt_texts: list[str] = []

    class CapturingLLM:
        async def extract(self, text, system_prompt, response_model, **kwargs):
            prompt_texts.append(text)
            from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
            from alayaos_core.llm.interface import LLMUsage

            result = PanoramicResult(actions=[])
            usage = LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.0)
            return result, usage

    session = _make_session()

    panoramic = PanoramicPass(llm_service=CapturingLLM(), session=session)
    await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    combined_prompt = "\n".join(prompt_texts)
    assert "garbage_hint" in combined_prompt


# ---------------------------------------------------------------------------
# Test: actions with unknown entity_ids are filtered out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_id_validation_rejects_unknown_uuids():
    """Actions referencing non-existent entity UUIDs are silently dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    # Only one real entity in the run
    real_entity_id = uuid.uuid4()
    fake_entity_id = uuid.uuid4()  # not in the entity list

    actions = [
        {
            "action": "remove_noise",
            "entity_id": str(fake_entity_id),  # unknown UUID
            "params": {"reason": "garbage"},
            "confidence": 0.9,
            "rationale": "unknown entity",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    entity = _make_entity("real-entity", entity_id=real_entity_id)
    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    # The action referencing fake_entity_id must be filtered out
    for action in result.actions:
        assert action.entity_id != fake_entity_id, f"Action referencing unknown UUID {fake_entity_id} was not filtered"


# ---------------------------------------------------------------------------
# Test: scalability cap logs warning when entity count > threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalability_cap_logs_warning():
    """When entity count exceeds the constructor cap, a structlog warning is emitted."""
    import structlog.testing

    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass

    fake_llm = _make_fake_llm_with_actions([])
    session = _make_session()

    # Create 10 entities but set max to 5 so cap fires
    entities = [_make_entity(f"Entity-{i}") for i in range(10)]

    panoramic = PanoramicPass(llm_service=fake_llm, session=session, max_entities=5)

    with structlog.testing.capture_logs() as cap_logs:
        await panoramic.run(
            workspace_id=uuid.uuid4(),
            entities=entities,
            entity_types=[],
            claims_by_entity={},
            relations_by_entity={},
        )

    # A warning must have been emitted about the cap
    warning_events = [entry for entry in cap_logs if entry.get("log_level") == "warning"]
    assert len(warning_events) >= 1, f"Expected at least one warning, got: {cap_logs}"
    # The event key should indicate a panoramic cap warning
    event_names = [e.get("event", "") for e in warning_events]
    assert any("panoramic" in ev or "cap" in ev or "max" in ev for ev in event_names), (
        f"Expected a panoramic cap warning, got events: {event_names}"
    )


# ---------------------------------------------------------------------------
# Test: PanoramicAction and PanoramicResult schema validation
# ---------------------------------------------------------------------------


def test_panoramic_action_schema_validation():
    """PanoramicAction rejects confidence outside [0, 1]."""
    from pydantic import ValidationError

    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction

    with pytest.raises(ValidationError):
        PanoramicAction(
            action="remove_noise",
            entity_id=None,
            params={},
            confidence=1.5,  # invalid: > 1.0
            rationale="test",
        )


def test_panoramic_action_rationale_max_length():
    """PanoramicAction rejects rationale longer than 280 chars."""
    from pydantic import ValidationError

    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction

    with pytest.raises(ValidationError):
        PanoramicAction(
            action="remove_noise",
            entity_id=None,
            params={},
            confidence=0.8,
            rationale="x" * 281,  # too long
        )


def test_panoramic_result_schema():
    """PanoramicResult holds a list of actions."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult

    result = PanoramicResult(
        actions=[
            PanoramicAction(
                action="rewrite",
                entity_id=uuid.uuid4(),
                params={"new_name": "Short Name"},
                confidence=0.85,
                rationale="Name was too long",
            )
        ]
    )
    assert len(result.actions) == 1
    assert result.actions[0].action == "rewrite"


# ---------------------------------------------------------------------------
# Test Fix 1: single-entity actions without entity_id are filtered out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_entity_action_without_entity_id_filtered():
    """remove_noise/reclassify/rewrite with entity_id=None are dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    entity = _make_entity("real-entity")
    actions = [
        {
            "action": "remove_noise",
            "entity_id": None,  # missing entity_id — must be rejected
            "params": {},
            "confidence": 0.9,
            "rationale": "noise entity",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "remove_noise with entity_id=None must be filtered out"


@pytest.mark.asyncio
async def test_reclassify_without_entity_id_filtered():
    """reclassify with entity_id=None is dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    entity = _make_entity("some-entity")
    actions = [
        {
            "action": "reclassify",
            "entity_id": None,
            "params": {"from_type": "person", "to_type": "project"},
            "confidence": 0.8,
            "rationale": "wrong type",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "reclassify with entity_id=None must be filtered out"


@pytest.mark.asyncio
async def test_rewrite_without_entity_id_filtered():
    """rewrite with entity_id=None is dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    entity = _make_entity("some-entity")
    actions = [
        {
            "action": "rewrite",
            "entity_id": None,
            "params": {"new_name": "Short Name"},
            "confidence": 0.7,
            "rationale": "name too long",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "rewrite with entity_id=None must be filtered out"


# ---------------------------------------------------------------------------
# Test Fix 2: create_from_cluster with invalid child_ids is filtered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_from_cluster_with_invalid_child_ids_filtered():
    """create_from_cluster referencing unknown child_ids is dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    real_entity = _make_entity("task-a")
    fake_child_id = uuid.uuid4()  # not in entity list

    actions = [
        {
            "action": "create_from_cluster",
            "entity_id": None,
            "params": {
                "child_ids": [str(fake_child_id)],
                "entity_type": "project",
                "name": "New Project",
                "description": "cluster of tasks",
            },
            "confidence": 0.75,
            "rationale": "cluster detected",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[real_entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "create_from_cluster with unknown child_ids must be filtered out"


@pytest.mark.asyncio
async def test_create_from_cluster_with_valid_child_ids_passes():
    """create_from_cluster referencing all valid child_ids is kept."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    child_a = _make_entity("task-a")
    child_b = _make_entity("task-b")
    child_c = _make_entity("task-c")

    actions = [
        {
            "action": "create_from_cluster",
            "entity_id": None,
            "params": {
                "child_ids": [str(child_a.id), str(child_b.id), str(child_c.id)],
                "entity_type": "project",
                "name": "New Project",
                "description": "cluster of tasks",
            },
            "confidence": 0.85,
            "rationale": "cluster detected",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[child_a, child_b, child_c],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 1, "create_from_cluster with all valid child_ids must pass through"


# ---------------------------------------------------------------------------
# Test Fix 2: link_cross_type with invalid source_id / target_id is filtered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_cross_type_with_invalid_source_id_filtered():
    """link_cross_type referencing unknown source_id is dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    real_entity = _make_entity("entity-a")
    fake_source_id = uuid.uuid4()

    actions = [
        {
            "action": "link_cross_type",
            "entity_id": None,
            "params": {
                "source_id": str(fake_source_id),
                "target_id": str(real_entity.id),
                "relation_type": "part_of",
            },
            "confidence": 0.8,
            "rationale": "related entities",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[real_entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "link_cross_type with unknown source_id must be filtered out"


@pytest.mark.asyncio
async def test_link_cross_type_with_invalid_target_id_filtered():
    """link_cross_type referencing unknown target_id is dropped."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    real_entity = _make_entity("entity-a")
    fake_target_id = uuid.uuid4()

    actions = [
        {
            "action": "link_cross_type",
            "entity_id": None,
            "params": {
                "source_id": str(real_entity.id),
                "target_id": str(fake_target_id),
                "relation_type": "part_of",
            },
            "confidence": 0.8,
            "rationale": "related entities",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[real_entity],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 0, "link_cross_type with unknown target_id must be filtered out"


@pytest.mark.asyncio
async def test_link_cross_type_with_valid_ids_passes():
    """link_cross_type with both valid source and target IDs is kept."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicPass, PanoramicResult

    entity_a = _make_entity("entity-a")
    entity_b = _make_entity("entity-b")

    actions = [
        {
            "action": "link_cross_type",
            "entity_id": None,
            "params": {
                "source_id": str(entity_a.id),
                "target_id": str(entity_b.id),
                "relation_type": "part_of",
            },
            "confidence": 0.9,
            "rationale": "clearly related",
        }
    ]
    fake_llm = _make_fake_llm_with_actions(actions)
    session = _make_session()

    panoramic = PanoramicPass(llm_service=fake_llm, session=session)
    result = await panoramic.run(
        workspace_id=uuid.uuid4(),
        entities=[entity_a, entity_b],
        entity_types=[],
        claims_by_entity={},
        relations_by_entity={},
    )

    assert isinstance(result, PanoramicResult)
    assert len(result.actions) == 1, "link_cross_type with valid source and target IDs must pass through"
