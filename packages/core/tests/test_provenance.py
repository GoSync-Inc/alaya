"""Provenance coverage tests — verify extraction_run_id and source_event_id on all writes."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.schemas import (
    ExtractedClaim,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)


def _make_event(event_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.is_extracted = False
    return event


def _make_run(run_id: uuid.UUID | None = None, event_id: uuid.UUID | None = None) -> MagicMock:
    run = MagicMock()
    run.id = run_id or uuid.uuid4()
    run.event_id = event_id or uuid.uuid4()
    run.resolver_decisions = []
    return run


# ─── Entity provenance: extraction_run_id ─────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_has_extraction_run_id() -> None:
    """Every entity.create call must include extraction_run_id."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)

    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(name="Alice", entity_type="person", confidence=0.9),
            ExtractedEntity(name="Bob", entity_type="person", confidence=0.9),
        ],
        relations=[],
        claims=[],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    alice_entity = MagicMock()
    alice_entity.id = uuid.uuid4()
    alice_entity.name = "Alice"
    alice_entity.aliases = []

    bob_entity = MagicMock()
    bob_entity.id = uuid.uuid4()
    bob_entity.name = "Bob"
    bob_entity.aliases = []

    entity_type_id = uuid.uuid4()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock(side_effect=[alice_entity, bob_entity])

    mock_entity_type_repo = AsyncMock()
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    mock_run_repo = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_relation_repo = AsyncMock()
    mock_claim_repo = AsyncMock()
    mock_predicate_repo = AsyncMock()

    llm = MagicMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_entity_type_repo),
    ):
        await atomic_write(extraction, event, run, session, llm)

    # Every entity.create call must pass extraction_run_id
    assert mock_entity_repo.create.call_count == 2
    for entity_call in mock_entity_repo.create.call_args_list:
        kwargs = entity_call.kwargs
        assert "extraction_run_id" in kwargs, f"entity.create missing extraction_run_id: {kwargs}"
        assert kwargs["extraction_run_id"] == run_id


# ─── Claim provenance: extraction_run_id + source_event_id ───────────────────


@pytest.mark.asyncio
async def test_claim_has_extraction_run_id_and_source_event_id() -> None:
    """Every claim.create call must include extraction_run_id and source_event_id."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)

    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Charlie", entity_type="person", confidence=0.9)],
        relations=[],
        claims=[
            ExtractedClaim(
                entity="Charlie",
                predicate="status",
                value="active",
                value_type="text",
                confidence=0.9,
            ),
            ExtractedClaim(
                entity="Charlie",
                predicate="role",
                value="engineer",
                value_type="text",
                confidence=0.9,
            ),
        ],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    charlie_id = uuid.uuid4()
    charlie_entity = MagicMock()
    charlie_entity.id = charlie_id
    charlie_entity.name = "Charlie"
    charlie_entity.aliases = []

    entity_type_id = uuid.uuid4()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock(return_value=charlie_entity)

    mock_entity_type_repo = AsyncMock()
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    predicate_def = MagicMock()
    predicate_def.id = uuid.uuid4()
    predicate_def.supersession_strategy = "latest_wins"

    mock_predicate_repo = AsyncMock()
    mock_predicate_repo.get_by_slug = AsyncMock(return_value=predicate_def)

    claim_1 = MagicMock()
    claim_1.id = uuid.uuid4()
    claim_2 = MagicMock()
    claim_2.id = uuid.uuid4()

    mock_claim_repo = AsyncMock()
    mock_claim_repo.create = AsyncMock(side_effect=[claim_1, claim_2])
    mock_claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[])

    mock_run_repo = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_relation_repo = AsyncMock()

    llm = MagicMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_entity_type_repo),
    ):
        await atomic_write(extraction, event, run, session, llm)

    # Every claim.create call must pass extraction_run_id and source_event_id
    assert mock_claim_repo.create.call_count == 2
    for claim_call in mock_claim_repo.create.call_args_list:
        kwargs = claim_call.kwargs
        assert "extraction_run_id" in kwargs, f"claim.create missing extraction_run_id: {kwargs}"
        assert kwargs["extraction_run_id"] == run_id
        assert "source_event_id" in kwargs, f"claim.create missing source_event_id: {kwargs}"
        assert kwargs["source_event_id"] == event_id


# ─── Relation provenance: extraction_run_id ──────────────────────────────────


@pytest.mark.asyncio
async def test_relation_has_extraction_run_id() -> None:
    """Every relation.create call must include extraction_run_id."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)

    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(name="Diana", entity_type="person", confidence=0.9),
            ExtractedEntity(name="Team Alpha", entity_type="team", confidence=0.9),
        ],
        relations=[
            ExtractedRelation(
                source_entity="Diana",
                target_entity="Team Alpha",
                relation_type="member_of",
                confidence=0.9,
            )
        ],
        claims=[],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    diana_id = uuid.uuid4()
    diana_entity = MagicMock()
    diana_entity.id = diana_id
    diana_entity.name = "Diana"
    diana_entity.aliases = []

    team_id = uuid.uuid4()
    team_entity = MagicMock()
    team_entity.id = team_id
    team_entity.name = "Team Alpha"
    team_entity.aliases = []

    entity_type_id = uuid.uuid4()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock(side_effect=[diana_entity, team_entity])

    mock_entity_type_repo = AsyncMock()
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    mock_relation_repo = AsyncMock()
    mock_relation_repo.create = AsyncMock(return_value=MagicMock())

    mock_run_repo = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_claim_repo = AsyncMock()
    mock_predicate_repo = AsyncMock()

    llm = MagicMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_entity_type_repo),
    ):
        await atomic_write(extraction, event, run, session, llm)

    # Every relation.create call must pass extraction_run_id
    assert mock_relation_repo.create.call_count == 1
    for relation_call in mock_relation_repo.create.call_args_list:
        kwargs = relation_call.kwargs
        assert "extraction_run_id" in kwargs, f"relation.create missing extraction_run_id: {kwargs}"
        assert kwargs["extraction_run_id"] == run_id
