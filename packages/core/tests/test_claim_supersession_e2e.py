"""Claim supersession E2E tests — all four policies end-to-end with mocked repos."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.schemas import ExtractedClaim


def _make_predicate(strategy: str) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.supersession_strategy = strategy
    return p


def _make_event(occurred_at: datetime) -> MagicMock:
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = occurred_at
    event.created_at = occurred_at
    event.id = uuid.uuid4()
    return event


def _make_run() -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    return run


def _make_existing_claim(claim_id: uuid.UUID, value: dict, observed_at: datetime) -> MagicMock:
    c = MagicMock()
    c.id = claim_id
    c.value = value
    c.observed_at = observed_at
    c.created_at = observed_at
    c.status = "active"
    return c


# ─── Policy 1: latest_wins — newer supersedes older ──────────────────────────


@pytest.mark.asyncio
async def test_latest_wins_newer_supersedes_older() -> None:
    """latest_wins: a newer claim supersedes the existing one."""
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    existing_at = datetime(2024, 1, 1, tzinfo=UTC)
    new_at = datetime(2024, 6, 1, tzinfo=UTC)

    old_claim = _make_existing_claim(old_id, {"text": "engineer"}, existing_at)
    new_claim = _make_existing_claim(new_id, {"text": "lead"}, new_at)

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock()
    claim_repo.update_status = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("latest_wins"))

    event = _make_event(new_at)
    run = _make_run()

    extracted = ExtractedClaim(entity="Alice", predicate="role", value="lead", confidence=0.9)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is new_claim
    claim_repo.mark_superseded.assert_called_once_with(old_id, new_id, new_at)


# ─── Policy 1: latest_wins — late-arriving claim gets superseded ──────────────


@pytest.mark.asyncio
async def test_latest_wins_late_arriving_is_superseded() -> None:
    """latest_wins: a late-arriving claim with older observed_at is itself superseded."""
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    # The existing claim is from June; the new claim arrives late from January
    existing_at = datetime(2024, 6, 1, tzinfo=UTC)
    late_at = datetime(2024, 1, 1, tzinfo=UTC)

    existing_claim = _make_existing_claim(old_id, {"text": "lead"}, existing_at)
    late_claim = _make_existing_claim(new_id, {"text": "engineer"}, late_at)

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=late_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[existing_claim, late_claim])
    claim_repo.mark_superseded = AsyncMock()
    claim_repo.update_status = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("latest_wins"))

    event = _make_event(late_at)
    run = _make_run()

    extracted = ExtractedClaim(entity="Alice", predicate="role", value="engineer", confidence=0.9)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is late_claim
    # The newly created late claim should be superseded by the existing newer claim
    claim_repo.mark_superseded.assert_called_once_with(new_id, old_id, existing_claim.observed_at)


# ─── Policy 2: explicit_only — high confidence supersedes ────────────────────


@pytest.mark.asyncio
async def test_explicit_only_high_confidence_supersedes() -> None:
    """explicit_only: confidence >= 0.85, different value, newer date → supersedes."""
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    existing_at = datetime(2024, 1, 1, tzinfo=UTC)
    new_at = datetime(2024, 6, 1, tzinfo=UTC)

    old_claim = _make_existing_claim(old_id, {"text": "engineer"}, existing_at)
    new_claim = _make_existing_claim(new_id, {"text": "staff-engineer"}, new_at)

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock()
    claim_repo.update_status = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("explicit_only"))

    event = _make_event(new_at)
    run = _make_run()

    # confidence >= 0.85 → should supersede
    extracted = ExtractedClaim(entity="Alice", predicate="role", value="staff-engineer", confidence=0.9)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is new_claim
    claim_repo.mark_superseded.assert_called_once_with(old_id, new_id, new_at)
    claim_repo.update_status.assert_not_called()


# ─── Policy 2: explicit_only — low confidence → disputed ─────────────────────


@pytest.mark.asyncio
async def test_explicit_only_low_confidence_disputed() -> None:
    """explicit_only: confidence < 0.85, different value → claim set to disputed."""
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    existing_at = datetime(2024, 1, 1, tzinfo=UTC)
    new_at = datetime(2024, 6, 1, tzinfo=UTC)

    old_claim = _make_existing_claim(old_id, {"text": "engineer"}, existing_at)
    new_claim = _make_existing_claim(new_id, {"text": "contractor"}, new_at)

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock()
    claim_repo.update_status = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("explicit_only"))

    event = _make_event(new_at)
    run = _make_run()

    # confidence < 0.85 → should be disputed
    extracted = ExtractedClaim(entity="Alice", predicate="role", value="contractor", confidence=0.7)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is new_claim
    claim_repo.mark_superseded.assert_not_called()
    claim_repo.update_status.assert_called_once_with(new_id, "disputed")


# ─── Policy 3: accumulate — both values active when different ─────────────────


@pytest.mark.asyncio
async def test_accumulate_different_values_both_active() -> None:
    """accumulate: two claims with different values both remain active."""
    from alayaos_core.extraction.writer import write_claim

    new_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    event_at = datetime(2024, 6, 1, tzinfo=UTC)

    new_claim = _make_existing_claim(new_id, {"text": "backend"}, event_at)

    claim_repo = AsyncMock()
    # Existing value is "frontend", new is "backend"
    claim_repo.get_active_values_for_entity_predicate = AsyncMock(return_value=[{"text": "frontend"}])
    claim_repo.create = AsyncMock(return_value=new_claim)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("accumulate"))

    event = _make_event(event_at)
    run = _make_run()

    extracted = ExtractedClaim(entity="Alice", predicate="skills", value="backend", confidence=0.9)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is new_claim
    claim_repo.create.assert_called_once()


# ─── Policy 3: accumulate — duplicate value is skipped ───────────────────────


@pytest.mark.asyncio
async def test_accumulate_duplicate_value_skipped() -> None:
    """accumulate: duplicate value results in no new claim (returns None)."""
    from alayaos_core.extraction.writer import write_claim

    entity_id = uuid.uuid4()
    event_at = datetime(2024, 6, 1, tzinfo=UTC)

    claim_repo = AsyncMock()
    # Existing active value matches the new claim value
    claim_repo.get_active_values_for_entity_predicate = AsyncMock(return_value=[{"text": "frontend"}])
    claim_repo.create = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate("accumulate"))

    event = _make_event(event_at)
    run = _make_run()

    extracted = ExtractedClaim(entity="Alice", predicate="skills", value="frontend", confidence=0.9)

    result = await write_claim(extracted, entity_id, event, run, claim_repo, predicate_repo, {})

    assert result is None
    claim_repo.create.assert_not_called()
