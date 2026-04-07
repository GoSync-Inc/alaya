"""Tests for pipeline.py — extraction pipeline orchestration."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_event(
    event_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    access_level: str = "public",
    raw_text: str | None = "test content",
) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.access_level = access_level
    event.source_type = "manual"
    event.source_id = "test-src"
    event.content = {"text": raw_text or ""}
    event.raw_text = raw_text
    event.occurred_at = datetime(2024, 1, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    event.is_extracted = False
    return event


def _make_run(
    run_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    status: str = "pending",
    event_id: uuid.UUID | None = None,
    raw_extraction: dict | None = None,
) -> MagicMock:
    run = MagicMock()
    run.id = run_id or uuid.uuid4()
    run.workspace_id = workspace_id or uuid.uuid4()
    run.status = status
    run.event_id = event_id or uuid.uuid4()
    run.raw_extraction = raw_extraction
    run.resolver_decisions = []
    return run


# ─── should_extract tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_extract_public_allowed() -> None:
    """Public access level: extraction should proceed."""
    from alayaos_core.extraction.pipeline import should_extract

    session = MagicMock()
    run = _make_run()
    run_repo = AsyncMock()
    run_repo.update_status = AsyncMock()

    event = _make_event(access_level="public")
    result = await should_extract(event, run, run_repo, session)

    assert result is True
    run_repo.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_should_extract_restricted_skipped() -> None:
    """Restricted access level: should_extract returns False and sets run status=skipped."""
    from alayaos_core.extraction.pipeline import should_extract

    session = MagicMock()
    run = _make_run()
    run_repo = AsyncMock()
    run_repo.update_status = AsyncMock()

    event = _make_event(access_level="restricted")
    result = await should_extract(event, run, run_repo, session)

    assert result is False
    run_repo.update_status.assert_called_once_with(run.id, "skipped", error_message="access_level=restricted")


@pytest.mark.asyncio
async def test_should_extract_private_no_optin_skipped() -> None:
    """Private event without workspace opt-in: should skip."""
    from alayaos_core.extraction.pipeline import should_extract

    session = MagicMock()
    run = _make_run()
    run_repo = AsyncMock()
    run_repo.update_status = AsyncMock()

    event = _make_event(access_level="private")

    # Workspace WITHOUT extract_private opt-in
    workspace = MagicMock()
    workspace.settings = {}  # no extract_private key

    mock_ws_repo = AsyncMock()
    mock_ws_repo.get_by_id = AsyncMock(return_value=workspace)

    with patch("alayaos_core.extraction.pipeline.WorkspaceRepository", return_value=mock_ws_repo):
        result = await should_extract(event, run, run_repo, session)

    assert result is False
    run_repo.update_status.assert_called_once_with(run.id, "skipped", error_message="private without opt-in")


@pytest.mark.asyncio
async def test_should_extract_private_with_optin_allowed() -> None:
    """Private event WITH workspace opt-in: extraction should proceed."""
    from alayaos_core.extraction.pipeline import should_extract

    session = MagicMock()
    run = _make_run()
    run_repo = AsyncMock()
    run_repo.update_status = AsyncMock()

    event = _make_event(access_level="private")

    workspace = MagicMock()
    workspace.settings = {"extract_private": True}

    mock_ws_repo = AsyncMock()
    mock_ws_repo.get_by_id = AsyncMock(return_value=workspace)

    with patch("alayaos_core.extraction.pipeline.WorkspaceRepository", return_value=mock_ws_repo):
        result = await should_extract(event, run, run_repo, session)

    assert result is True
    run_repo.update_status.assert_not_called()


# ─── run_extraction tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_extraction_idempotent_skip() -> None:
    """run_extraction: if run.status == 'completed', return None (idempotent)."""
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.pipeline import run_extraction
    from alayaos_core.extraction.preprocessor import Preprocessor

    run_id = uuid.uuid4()
    event_id = uuid.uuid4()

    completed_run = _make_run(run_id=run_id, status="completed")
    event = _make_event(event_id=event_id)

    session = MagicMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=completed_run)

    llm = AsyncMock()
    preprocessor = MagicMock(spec=Preprocessor)
    extractor = MagicMock(spec=Extractor)

    with (
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
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

    assert result is None
    preprocessor.chunk.assert_not_called()


# ─── run_write tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_write_no_raw_extraction_fails() -> None:
    """run_write: run with no raw_extraction sets status=failed."""
    from alayaos_core.extraction.pipeline import run_write

    run_id = uuid.uuid4()
    event_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    run = _make_run(run_id=run_id, status="writing", event_id=event_id, raw_extraction=None)
    run.workspace_id = workspace_id
    event = _make_event(event_id=event_id, workspace_id=workspace_id)

    session = MagicMock()

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)

    llm = AsyncMock()

    with (
        patch("alayaos_core.extraction.pipeline.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.pipeline.EventRepository", return_value=mock_event_repo),
    ):
        result = await run_write(
            run_id=run_id,
            session=session,
            llm=llm,
            redis=None,
        )

    assert result is None
    mock_run_repo.update_status.assert_called_with(run.id, "failed", error_message="no raw_extraction")


# ─── workspace lock tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_lock_acquire_release() -> None:
    """acquire_workspace_lock + release_workspace_lock with mock redis."""
    from alayaos_core.extraction.writer import acquire_workspace_lock, release_workspace_lock

    workspace_id = str(uuid.uuid4())

    # Mock redis: set returns True (acquired), eval returns 1 (released)
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.eval = AsyncMock(return_value=1)

    result_token = await acquire_workspace_lock(redis, workspace_id, timeout=30)
    assert result_token is not None
    redis.set.assert_called_once_with(
        f"extraction:write_lock:{workspace_id}",
        result_token,
        nx=True,
        ex=30,
    )

    released = await release_workspace_lock(redis, workspace_id, result_token)
    assert released is True
    redis.eval.assert_called_once()


@pytest.mark.asyncio
async def test_workspace_lock_acquire_fails_when_already_locked() -> None:
    """acquire_workspace_lock returns None when lock is already held."""
    from alayaos_core.extraction.writer import acquire_workspace_lock

    workspace_id = str(uuid.uuid4())

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=None)  # NX fail → returns None

    result_token = await acquire_workspace_lock(redis, workspace_id, timeout=30)
    assert result_token is None
