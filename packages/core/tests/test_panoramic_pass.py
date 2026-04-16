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
    """When entity count > CONSOLIDATOR_PANORAMIC_MAX_ENTITIES, a structlog warning is emitted."""
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
