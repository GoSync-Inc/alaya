"""End-to-end extraction pipeline test with mocked dependencies."""

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
from alayaos_core.llm.fake import FakeLLMAdapter


def _make_event(
    event_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.access_level = "public"
    event.source_type = "slack"
    event.source_id = "C123/T456"
    event.content = {"text": ""}
    event.raw_text = "Alice is the owner of Project Phoenix. Deadline is April 15."
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
    run.tokens_in = 0
    run.tokens_out = 0
    run.tokens_cached = 0
    run.cost_usd = 0.0
    run.llm_provider = None
    run.llm_model = None
    return run


# ─── Test 1: run_extraction stores raw extraction ─────────────────────────────


@pytest.mark.asyncio
async def test_run_extraction_stores_raw_extraction() -> None:
    """run_extraction: result is stored via run_repo.store_raw_extraction."""
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.pipeline import run_extraction
    from alayaos_core.extraction.preprocessor import Preprocessor

    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)

    # FakeLLMAdapter returns minimal ExtractionResult by default
    llm = FakeLLMAdapter()
    preprocessor = Preprocessor()
    extractor = Extractor(llm, gleaning_enabled=False)

    session = MagicMock()
    session.flush = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.store_raw_extraction = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()

    with (
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.config.Settings"),
    ):
        result = await run_extraction(
            event_id=event_id,
            run_id=run_id,
            session=session,
            llm=llm,
            preprocessor=preprocessor,
            extractor=extractor,
            entity_types=[],
            predicates=[],
        )

    assert result is not None
    assert isinstance(result, ExtractionResult)
    mock_run_repo.store_raw_extraction.assert_called_once()
    stored_data = mock_run_repo.store_raw_extraction.call_args[0]
    assert stored_data[0] == run_id
    assert "entities" in stored_data[1]
    assert "claims" in stored_data[1]


# ─── Test 2: run_write creates entities, claims, relations ────────────────────


@pytest.mark.asyncio
async def test_run_write_creates_entities_claims_relations() -> None:
    """run_write: calls atomic_write which creates entities, claims, relations via repos."""
    from alayaos_core.extraction.pipeline import run_write

    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)

    extraction_data = ExtractionResult(
        entities=[
            ExtractedEntity(name="Alice", entity_type="person", confidence=0.9),
            ExtractedEntity(name="Project Phoenix", entity_type="project", confidence=0.9),
        ],
        relations=[
            ExtractedRelation(
                source_entity="Alice",
                target_entity="Project Phoenix",
                relation_type="member_of",
                confidence=0.9,
            )
        ],
        claims=[
            ExtractedClaim(
                entity="Project Phoenix",
                predicate="owner",
                value="Alice",
                value_type="entity_ref",
                confidence=0.9,
            )
        ],
    )

    run = _make_run(
        run_id=run_id,
        event_id=event_id,
        status="pending",
        raw_extraction=extraction_data.model_dump(),
    )

    session = MagicMock()
    session.flush = AsyncMock()

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=event)

    # Mock repos used inside atomic_write
    alice_id = uuid.uuid4()
    phoenix_id = uuid.uuid4()
    entity_type_id = uuid.uuid4()

    alice_entity = MagicMock()
    alice_entity.id = alice_id
    alice_entity.name = "Alice"
    alice_entity.aliases = []

    phoenix_entity = MagicMock()
    phoenix_entity.id = phoenix_id
    phoenix_entity.name = "Project Phoenix"
    phoenix_entity.aliases = []

    mock_entity_repo = AsyncMock()
    # list returns empty (no existing entities)
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)

    # Alternate returns for create: first Alice, then Project Phoenix
    mock_entity_repo.create = AsyncMock(side_effect=[alice_entity, phoenix_entity])

    mock_relation_repo = AsyncMock()
    mock_relation_repo.create = AsyncMock(return_value=MagicMock())

    mock_claim = MagicMock()
    mock_claim.id = uuid.uuid4()
    mock_claim_repo = AsyncMock()
    mock_claim_repo.create = AsyncMock(return_value=mock_claim)
    mock_claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[mock_claim])

    mock_predicate_repo = AsyncMock()
    predicate_def = MagicMock()
    predicate_def.id = uuid.uuid4()
    predicate_def.supersession_strategy = "latest_wins"
    mock_predicate_repo.get_by_slug = AsyncMock(return_value=predicate_def)

    mock_entity_type_repo = AsyncMock()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    llm = FakeLLMAdapter()

    mock_workspace_repo = AsyncMock()
    mock_workspace_repo.get_by_id_for_update = AsyncMock(return_value=MagicMock())

    with (
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.WorkspaceRepository", return_value=mock_workspace_repo),
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_entity_type_repo),
    ):
        counters = await run_write(
            run_id=run_id,
            session=session,
            llm=llm,
            redis=None,
        )

    assert counters is not None
    assert counters["entities_created"] == 2
    assert counters["relations_created"] == 1
    assert counters["claims_created"] == 1


# ─── Test 3: event.is_extracted = True after write ────────────────────────────


@pytest.mark.asyncio
async def test_run_write_marks_event_as_extracted() -> None:
    """atomic_write marks event.is_extracted = True."""
    from alayaos_core.extraction.pipeline import run_write

    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    assert event.is_extracted is False

    extraction_data = ExtractionResult(entities=[], relations=[], claims=[])
    run = _make_run(
        run_id=run_id,
        event_id=event_id,
        status="pending",
        raw_extraction=extraction_data.model_dump(),
    )

    session = MagicMock()
    session.flush = AsyncMock()

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=event)

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))

    mock_relation_repo = AsyncMock()
    mock_claim_repo = AsyncMock()
    mock_predicate_repo = AsyncMock()

    llm = FakeLLMAdapter()

    mock_workspace_repo = AsyncMock()
    mock_workspace_repo.get_by_id_for_update = AsyncMock(return_value=MagicMock())

    with (
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.WorkspaceRepository", return_value=mock_workspace_repo),
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
    ):
        await run_write(run_id=run_id, session=session, llm=llm, redis=None)

    assert event.is_extracted is True


# ─── Test 4: extraction_run counters updated ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_write_updates_run_counters() -> None:
    """atomic_write calls run_repo.update_counters with entity/claim counts."""
    from alayaos_core.extraction.pipeline import run_write

    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)

    extraction_data = ExtractionResult(
        entities=[ExtractedEntity(name="Bob", entity_type="person", confidence=0.9)],
        relations=[],
        claims=[],
    )
    run = _make_run(
        run_id=run_id,
        event_id=event_id,
        status="pending",
        raw_extraction=extraction_data.model_dump(),
    )

    session = MagicMock()
    session.flush = AsyncMock()

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.clear_raw_extraction = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=event)

    entity_id = uuid.uuid4()
    entity_type_id = uuid.uuid4()
    bob_entity = MagicMock()
    bob_entity.id = entity_id
    bob_entity.name = "Bob"
    bob_entity.aliases = []

    mock_entity_repo = AsyncMock()
    mock_entity_repo.list = AsyncMock(return_value=([], None, False))
    mock_entity_repo.get_by_external_id = AsyncMock(return_value=None)
    mock_entity_repo.create = AsyncMock(return_value=bob_entity)

    mock_entity_type_repo = AsyncMock()
    mock_entity_type_obj = MagicMock()
    mock_entity_type_obj.id = entity_type_id
    mock_entity_type_repo.get_by_slug = AsyncMock(return_value=mock_entity_type_obj)

    mock_relation_repo = AsyncMock()
    mock_claim_repo = AsyncMock()
    mock_predicate_repo = AsyncMock()

    llm = FakeLLMAdapter()

    mock_workspace_repo = AsyncMock()
    mock_workspace_repo.get_by_id_for_update = AsyncMock(return_value=MagicMock())

    with (
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.WorkspaceRepository", return_value=mock_workspace_repo),
        patch("alayaos_core.extraction.writer.EntityRepository", return_value=mock_entity_repo),
        patch("alayaos_core.extraction.writer.RelationRepository", return_value=mock_relation_repo),
        patch("alayaos_core.extraction.writer.ClaimRepository", return_value=mock_claim_repo),
        patch("alayaos_core.extraction.writer.PredicateRepository", return_value=mock_predicate_repo),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_entity_type_repo),
    ):
        await run_write(run_id=run_id, session=session, llm=llm, redis=None)

    mock_run_repo.update_counters.assert_called_once()
    call_kwargs = mock_run_repo.update_counters.call_args
    assert call_kwargs[0][0] == run_id
