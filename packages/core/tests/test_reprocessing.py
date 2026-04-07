"""Reprocessing tests — re-extraction of same event with mocked repos."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.schemas import (
    ExtractedClaim,
    ExtractedEntity,
    ExtractionResult,
)


def _make_event(event_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.access_level = "public"
    event.source_type = "slack"
    event.source_id = "C001/T001"
    event.content = {"text": ""}
    event.raw_text = "Alice is PM of Project Alpha."
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.is_extracted = False
    return event


def _make_run(
    run_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    status: str = "pending",
    raw_extraction: dict | None = None,
) -> MagicMock:
    run = MagicMock()
    run.id = run_id or uuid.uuid4()
    run.status = status
    run.event_id = event_id or uuid.uuid4()
    run.raw_extraction = raw_extraction
    run.resolver_decisions = []
    return run


def _make_existing_entity(name: str, entity_id: uuid.UUID | None = None) -> MagicMock:
    entity = MagicMock()
    entity.id = entity_id or uuid.uuid4()
    entity.name = name
    entity.aliases = []
    return entity


# ─── Test 1: First extraction creates entities ───────────────────────────────


@pytest.mark.asyncio
async def test_first_extraction_creates_entities() -> None:
    """First atomic_write creates new entities from raw_extraction."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)

    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Alice", entity_type="person", confidence=0.9)],
        relations=[],
        claims=[],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    alice_id = uuid.uuid4()
    alice_entity = _make_existing_entity("Alice", alice_id)

    entity_type_id = uuid.uuid4()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock(return_value=alice_entity)

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
        counters = await atomic_write(extraction, event, run, session, llm)

    assert counters["entities_created"] == 1
    mock_entity_repo.create.assert_called_once()
    # Verify extraction_run_id was passed to entity.create
    create_kwargs = mock_entity_repo.create.call_args.kwargs
    assert create_kwargs.get("extraction_run_id") == run_id


# ─── Test 2: Second extraction reuses existing entity (no duplicates) ─────────


@pytest.mark.asyncio
async def test_second_extraction_merges_existing_entity() -> None:
    """Second atomic_write with same entity name reuses existing (no duplicate)."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id_2 = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run2 = _make_run(run_id=run_id_2, event_id=event_id)

    # Second extraction has same entity name
    extraction2 = ExtractionResult(
        entities=[ExtractedEntity(name="Alice", entity_type="person", confidence=0.9)],
        relations=[],
        claims=[],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    # Alice already exists in the DB from first extraction
    alice_id = uuid.uuid4()
    alice_entity = _make_existing_entity("Alice", alice_id)

    mock_entity_repo = AsyncMock()
    # list returns Alice as existing entity
    mock_entity_repo.list = AsyncMock(return_value=([alice_entity], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock()  # should NOT be called

    mock_entity_type_repo = AsyncMock()
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
        counters = await atomic_write(extraction2, event, run2, session, llm)

    # Entity merged (not created new)
    assert counters["entities_created"] == 0
    assert counters["entities_merged"] == 1
    mock_entity_repo.create.assert_not_called()


# ─── Test 3: Claims supersede properly on reprocessing ───────────────────────


@pytest.mark.asyncio
async def test_reprocessing_claims_supersede_properly() -> None:
    """On reprocessing, new claims supersede old ones via latest_wins."""
    from alayaos_core.extraction.writer import atomic_write

    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id_2 = uuid.uuid4()

    # Second extraction with updated claim value
    event2 = _make_event(event_id=event_id, workspace_id=workspace_id)
    event2.occurred_at = datetime(2024, 9, 1, tzinfo=UTC)
    run2 = _make_run(run_id=run_id_2, event_id=event_id)

    extraction2 = ExtractionResult(
        entities=[ExtractedEntity(name="Alice", entity_type="person", confidence=0.9)],
        relations=[],
        claims=[
            ExtractedClaim(
                entity="Alice",
                predicate="status",
                value="promoted",
                value_type="text",
                confidence=0.9,
            )
        ],
    )

    session = MagicMock()
    session.flush = AsyncMock()

    alice_id = uuid.uuid4()
    alice_entity = _make_existing_entity("Alice", alice_id)

    # Old claim from first extraction
    old_claim_id = uuid.uuid4()
    old_claim = MagicMock()
    old_claim.id = old_claim_id
    old_claim.value = {"text": "active"}
    old_claim.observed_at = datetime(2024, 6, 1, tzinfo=UTC)
    old_claim.created_at = datetime(2024, 6, 1, tzinfo=UTC)

    new_claim_id = uuid.uuid4()
    new_claim = MagicMock()
    new_claim.id = new_claim_id
    new_claim.value = {"text": "promoted"}
    new_claim.observed_at = datetime(2024, 9, 1, tzinfo=UTC)

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([alice_entity], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock()

    entity_type_id = uuid.uuid4()
    mock_entity_type_repo = AsyncMock()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    predicate_def = MagicMock()
    predicate_def.id = uuid.uuid4()
    predicate_def.supersession_strategy = "latest_wins"

    mock_predicate_repo = AsyncMock()
    mock_predicate_repo.get_by_slug = AsyncMock(return_value=predicate_def)

    mock_claim_repo = AsyncMock()
    mock_claim_repo.create = AsyncMock(return_value=new_claim)
    mock_claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    mock_claim_repo.mark_superseded = AsyncMock()
    mock_claim_repo.update_status = AsyncMock()

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
        counters = await atomic_write(extraction2, event2, run2, session, llm)

    assert counters["claims_created"] == 1
    # Old claim was superseded by new claim
    mock_claim_repo.mark_superseded.assert_called_once_with(old_claim_id, new_claim_id, event2.occurred_at)
