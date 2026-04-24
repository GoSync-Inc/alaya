"""Tests for writer.py — value normalization, claim supersession, and atomic write."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── Task 1: normalize_claim_value ───────────────────────────────────────────


def test_normalize_claim_value_text() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("hello world", "text")
    assert result == {"text": "hello world"}


def test_normalize_claim_value_date() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("2024-03-15", "date", reference_date=datetime(2024, 1, 1, tzinfo=UTC))
    assert result == {
        "date": "2024-03-15",
        "iso": "2024-03-15T00:00:00+00:00",
        "normalized": True,
        "anchor": "2024-01-01T00:00:00+00:00",
        "reason": None,
    }


def test_normalize_claim_value_number() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("42.5", "number")
    assert result == {"number": 42.5, "raw": "42.5"}


def test_normalize_claim_value_boolean() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    assert normalize_claim_value("true", "boolean") == {"boolean": True}
    assert normalize_claim_value("false", "boolean") == {"boolean": False}
    assert normalize_claim_value("yes", "boolean") == {"boolean": True}
    assert normalize_claim_value("1", "boolean") == {"boolean": True}
    assert normalize_claim_value("0", "boolean") == {"boolean": False}


def test_normalize_claim_value_entity_ref() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("Alice Smith", "entity_ref")
    assert result == {"raw": "Alice Smith"}
    assert "entity_ref" not in result


def test_normalize_claim_value_entity_ref_resolved() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    eid = str(uuid.uuid4())
    result = normalize_claim_value("Alice Smith", "entity_ref", resolved_entity_id=eid)
    assert result == {"raw": "Alice Smith", "entity_ref": eid}


def test_normalize_claim_value_number_invalid_fallback() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("not-a-number", "number")
    assert result == {"text": "not-a-number"}


def test_normalize_claim_value_unknown_type_fallback() -> None:
    from alayaos_core.extraction.writer import normalize_claim_value

    result = normalize_claim_value("some value", "json")
    assert result == {"text": "some value"}


# ─── Task 2: write_claim supersession ─────────────────────────────────────────


def _make_claim(
    claim_id: uuid.UUID, value: dict, observed_at: datetime | None = None, created_at: datetime | None = None
):
    """Make a minimal mock L2Claim."""
    c = MagicMock()
    c.id = claim_id
    c.value = value
    c.observed_at = observed_at
    c.created_at = created_at or datetime(2024, 1, 1, tzinfo=UTC)
    return c


def _make_predicate_def(supersession_strategy: str):
    pd = MagicMock()
    pd.id = uuid.uuid4()
    pd.supersession_strategy = supersession_strategy
    return pd


@pytest.mark.asyncio
async def test_write_claim_latest_wins_supersedes() -> None:
    """latest_wins: newer claim supersedes older one."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    old_claim = _make_claim(old_id, {"text": "old"}, datetime(2024, 1, 1, tzinfo=UTC))
    new_claim = _make_claim(new_id, {"text": "new"}, datetime(2024, 6, 1, tzinfo=UTC))

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock(return_value=None)
    claim_repo.update_status = AsyncMock(return_value=None)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("latest_wins"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="status",
        value="active",
        value_type="text",
        confidence=0.9,
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is new_claim
    claim_repo.mark_superseded.assert_called_once_with(old_id, new_id, event.occurred_at)


@pytest.mark.asyncio
async def test_write_claim_latest_wins_late_arriving() -> None:
    """latest_wins: older claim arriving late gets marked superseded itself."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    # new_claim.id is what claim_repo.create returns, but event.occurred_at is EARLIER
    late_claim = _make_claim(new_id, {"text": "old-data"}, datetime(2024, 1, 1, tzinfo=UTC))
    existing_claim = _make_claim(old_id, {"text": "newer-data"}, datetime(2024, 6, 1, tzinfo=UTC))

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=late_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[existing_claim, late_claim])
    claim_repo.mark_superseded = AsyncMock(return_value=None)
    claim_repo.update_status = AsyncMock(return_value=None)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("latest_wins"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    # Event occurred in January — late arrival
    event.occurred_at = datetime(2024, 1, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="status",
        value="old-status",
        value_type="text",
        confidence=0.9,
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is late_claim
    # The newly-created (late-arriving) claim should be superseded by the existing newer one
    claim_repo.mark_superseded.assert_called_once_with(new_id, old_id, existing_claim.observed_at)


@pytest.mark.asyncio
async def test_write_claim_explicit_only_supersedes() -> None:
    """explicit_only: high confidence + different value + newer → supersedes."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    old_claim = _make_claim(old_id, {"text": "old-role"}, datetime(2024, 1, 1, tzinfo=UTC))
    new_claim = _make_claim(new_id, {"text": "new-role"}, datetime(2024, 6, 1, tzinfo=UTC))

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock(return_value=None)
    claim_repo.update_status = AsyncMock(return_value=None)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("explicit_only"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="role",
        value="new-role",
        value_type="text",
        confidence=0.9,  # >= 0.85
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is new_claim
    claim_repo.mark_superseded.assert_called_once_with(old_id, new_id, event.occurred_at)


@pytest.mark.asyncio
async def test_write_claim_explicit_only_disputed() -> None:
    """explicit_only: low confidence + different value → disputed."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    old_claim = _make_claim(old_id, {"text": "old-role"}, datetime(2024, 1, 1, tzinfo=UTC))
    new_claim = _make_claim(new_id, {"text": "new-role"}, datetime(2024, 6, 1, tzinfo=UTC))

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=new_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[old_claim, new_claim])
    claim_repo.mark_superseded = AsyncMock(return_value=None)
    claim_repo.update_status = AsyncMock(return_value=None)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("explicit_only"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="role",
        value="new-role",
        value_type="text",
        confidence=0.7,  # < 0.85 → disputed
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is new_claim
    claim_repo.mark_superseded.assert_not_called()
    claim_repo.update_status.assert_called_once_with(new_id, "disputed")


@pytest.mark.asyncio
async def test_write_claim_accumulate_dedup() -> None:
    """accumulate: duplicate value returns None (dedup)."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    existing_value = {"text": "member"}

    claim_repo = AsyncMock()
    claim_repo.get_active_values_for_entity_predicate = AsyncMock(return_value=[existing_value])
    claim_repo.create = AsyncMock()

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("accumulate"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="member_of",
        value="member",
        value_type="text",
        confidence=0.9,
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is None
    claim_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_write_claim_accumulate_new() -> None:
    """accumulate: new value is written (not a dup)."""
    from alayaos_core.extraction.schemas import ExtractedClaim
    from alayaos_core.extraction.writer import write_claim

    new_id = uuid.uuid4()
    new_claim = _make_claim(new_id, {"text": "team-b"})

    claim_repo = AsyncMock()
    claim_repo.get_active_values_for_entity_predicate = AsyncMock(return_value=[{"text": "team-a"}])
    claim_repo.create = AsyncMock(return_value=new_claim)

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def("accumulate"))

    entity_id = uuid.uuid4()
    event = MagicMock()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Alice",
        predicate="member_of",
        value="team-b",
        value_type="text",
        confidence=0.9,
    )

    result, _ = await write_claim(
        claim=extracted_claim,
        entity_id=entity_id,
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is new_claim
    claim_repo.create.assert_called_once()
