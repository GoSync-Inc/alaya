"""Channel access extraction policy tests."""

import inspect
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.extractor import Extractor
from alayaos_core.extraction.pipeline import run_extraction, should_extract
from alayaos_core.extraction.preprocessor import Preprocessor
from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm.fake import FakeLLMAdapter


def _make_event(
    event_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    access_level: str = "channel",
) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.workspace_id = workspace_id
    event.access_level = access_level
    event.source_type = "slack"
    event.source_id = "C123"
    event.content = {"text": "Alice owns the onboarding checklist."}
    event.raw_text = "Alice owns the onboarding checklist."
    event.occurred_at = datetime(2026, 4, 24, tzinfo=UTC)
    event.created_at = datetime(2026, 4, 24, tzinfo=UTC)
    return event


def _make_run(run_id: uuid.UUID, event_id: uuid.UUID, workspace_id: uuid.UUID) -> MagicMock:
    run = MagicMock()
    run.id = run_id
    run.event_id = event_id
    run.workspace_id = workspace_id
    run.status = "pending"
    run.raw_extraction = None
    run.resolver_decisions = []
    return run


def test_pipeline_documents_channel_access_retrieval_tier() -> None:
    source = inspect.getsource(should_extract)

    assert 'access_level="channel" is tier 1 at retrieval' in source


@pytest.mark.asyncio
async def test_channel_event_extracts_like_public() -> None:
    """Channel events must still extract until retrieval-tier filtering is available."""
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    event = _make_event(event_id, workspace_id)
    run = _make_run(run_id, event_id, workspace_id)

    session = MagicMock()
    session.flush = AsyncMock()
    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=event)
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.store_raw_extraction = AsyncMock()

    with (
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.config.Settings"),
    ):
        result = await run_extraction(
            event_id=event_id,
            run_id=run_id,
            session=session,
            llm=FakeLLMAdapter(),
            preprocessor=Preprocessor(),
            extractor=Extractor(FakeLLMAdapter(), gleaning_enabled=False),
            entity_types=[],
            predicates=[],
        )

    assert isinstance(result, ExtractionResult)
    mock_run_repo.store_raw_extraction.assert_called_once()
    assert ("skipped",) not in [call.args[1:] for call in mock_run_repo.update_status.await_args_list]
