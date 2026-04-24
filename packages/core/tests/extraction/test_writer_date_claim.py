"""Writer integration coverage for date-typed claims."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing

from alayaos_core.extraction.schemas import ExtractedClaim
from alayaos_core.extraction.writer import write_claim


def _make_predicate_def() -> MagicMock:
    predicate = MagicMock()
    predicate.id = uuid.uuid4()
    predicate.supersession_strategy = "latest_wins"
    return predicate


@pytest.mark.asyncio
async def test_write_claim_normalizes_relative_date_with_event_anchor() -> None:
    claim_repo = AsyncMock()
    created_claim = MagicMock()
    created_claim.id = uuid.uuid4()
    claim_repo.create = AsyncMock(return_value=created_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[created_claim])

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def())

    event = MagicMock()
    event.id = uuid.uuid4()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2026, 4, 25, tzinfo=UTC)
    event.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Launch",
        predicate="deadline",
        value="завтра",
        value_type="date",
        confidence=0.9,
    )

    result, superseded = await write_claim(
        claim=extracted_claim,
        entity_id=uuid.uuid4(),
        event=event,
        run=run,
        claim_repo=claim_repo,
        predicate_repo=predicate_repo,
        entity_name_to_id={},
    )

    assert result is created_claim
    assert superseded == 0
    assert claim_repo.create.call_args.kwargs["value"] == {
        "date": "завтра",
        "iso": "2026-04-26T00:00:00+00:00",
        "normalized": True,
        "anchor": "2026-04-25T00:00:00+00:00",
        "reason": None,
    }


@pytest.mark.asyncio
async def test_write_claim_logs_date_normalization_failure_after_create() -> None:
    claim_repo = AsyncMock()
    created_claim = MagicMock()
    created_claim.id = uuid.uuid4()
    claim_repo.create = AsyncMock(return_value=created_claim)
    claim_repo.get_active_for_entity_predicate = AsyncMock(return_value=[created_claim])

    predicate_repo = AsyncMock()
    predicate_repo.get_by_slug = AsyncMock(return_value=_make_predicate_def())

    event = MagicMock()
    event.id = uuid.uuid4()
    event.workspace_id = uuid.uuid4()
    event.occurred_at = datetime(2026, 4, 25, tzinfo=UTC)
    event.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    run = MagicMock()
    run.id = uuid.uuid4()

    extracted_claim = ExtractedClaim(
        entity="Launch",
        predicate="deadline",
        value="3000-01-01",
        value_type="date",
        confidence=0.9,
    )

    with structlog.testing.capture_logs() as logs:
        await write_claim(
            claim=extracted_claim,
            entity_id=uuid.uuid4(),
            event=event,
            run=run,
            claim_repo=claim_repo,
            predicate_repo=predicate_repo,
            entity_name_to_id={},
        )

    assert logs == [
        {
            "event": "claim.date_normalize_failed",
            "log_level": "info",
            "claim_id": str(created_claim.id),
            "event_id": str(event.id),
            "reason": "out_of_sanity_window",
            "raw": "3000-01-01",
        }
    ]
