"""End-to-end tests for the Cortex pipeline (job_cortex)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_event(text: str = "Team meeting to discuss Q3 roadmap.", source_type: str = "manual") -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.raw_text = text
    event.content = {}
    event.source_type = source_type
    event.source_id = "src-123"
    return event


def _make_run() -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.chunks_total = 0
    run.chunks_crystal = 0
    run.chunks_skipped = 0
    run.cortex_cost_usd = 0.0
    run.verification_changes = 0
    return run


def _make_chunk_obj() -> MagicMock:
    chunk = MagicMock()
    chunk.id = uuid.uuid4()
    chunk.classification_verified = False
    chunk.verification_changed = False
    return chunk


def _make_mock_session_factory():
    """Build a mock session factory following the same pattern as test_worker_rls.py."""
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.begin = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    mock_factory_inst = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )
    mock_factory = MagicMock(return_value=mock_factory_inst)
    return mock_factory, mock_session


def _mock_settings(*, threshold: float = 0.1, api_key: str = "") -> MagicMock:
    s = MagicMock()
    s.ANTHROPIC_API_KEY.get_secret_value.return_value = api_key
    s.CORTEX_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
    s.CORTEX_MAX_CHUNK_TOKENS = 3000
    s.CORTEX_CRYSTAL_THRESHOLD = threshold
    s.CORTEX_TRUNCATION_TOKENS = 800
    return s


# ── Test 1: Basic pipeline — chunks + traces created ─────────────────────────


@pytest.mark.asyncio
async def test_cortex_pipeline_creates_chunks_and_traces() -> None:
    """End-to-end: job_cortex creates L0Chunks and PipelineTraces for a simple event."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    event = _make_event("Team meeting to discuss Q3 roadmap and OKR alignment.")
    run = _make_run()
    mock_chunk = _make_chunk_obj()

    mock_factory, _mock_session = _make_mock_session_factory()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=mock_chunk)
    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock(return_value=MagicMock())

    original_rls = worker_tasks._set_workspace_context

    async def noop_rls(session, wid):
        pass

    worker_tasks._set_workspace_context = noop_rls  # type: ignore[assignment]

    try:
        with (
            patch("alayaos_core.worker.tasks.Settings", return_value=_mock_settings(threshold=0.1)),
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
            patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
            patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
            patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        ):
            result = await worker_tasks.job_cortex.original_func(event_id, run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original_rls  # type: ignore[assignment]

    assert mock_chunk_repo.create.called, "chunk_repo.create should have been called"
    assert mock_trace_repo.create.called, "trace_repo.create should have been called"
    assert result["status"] == "cortex_complete"
    assert result["event_id"] == event_id
    assert result["extraction_run_id"] == run_id
    assert result["chunks_total"] >= 1


# ── Test 2: Crystal selection based on FakeLLM (all 0.0 scores) ─────────────


@pytest.mark.asyncio
async def test_cortex_pipeline_crystal_selection_all_skipped_at_high_threshold() -> None:
    """FakeLLM returns realistic scores (max 0.6); with threshold=0.9 all chunks are NOT crystal."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    event = _make_event("We decided to adopt the new architecture framework.")
    run = _make_run()
    mock_chunk = _make_chunk_obj()

    mock_factory, _ = _make_mock_session_factory()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=mock_chunk)
    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock(return_value=MagicMock())

    original_rls = worker_tasks._set_workspace_context

    async def noop_rls(session, wid):
        pass

    worker_tasks._set_workspace_context = noop_rls  # type: ignore[assignment]

    try:
        with (
            patch("alayaos_core.worker.tasks.Settings", return_value=_mock_settings(threshold=0.9)),
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
            patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
            patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
            patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        ):
            result = await worker_tasks.job_cortex.original_func(event_id, run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original_rls  # type: ignore[assignment]

    # FakeLLM returns max 0.6 → threshold=0.9 → no crystal chunks
    assert result["chunks_crystal"] == 0
    assert result["chunks_total"] >= 1
    # Run counters were updated on the run object
    assert run.chunks_total == result["chunks_total"]
    assert run.chunks_crystal == 0


# ── Test 3: Feature flag routing ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_extract_routes_to_cortex_when_flag_enabled() -> None:
    """job_extract routes to job_cortex when FEATURE_FLAG_USE_CORTEX=True."""
    from alayaos_core.worker.tasks import job_extract

    mock_kiq = AsyncMock(return_value=None)

    with patch("alayaos_core.worker.tasks.Settings") as mock_settings_cls:
        mock_settings = MagicMock()
        mock_settings.FEATURE_FLAG_USE_CORTEX = True
        mock_settings.ANTHROPIC_API_KEY.get_secret_value.return_value = ""
        mock_settings_cls.return_value = mock_settings

        with patch("alayaos_core.worker.tasks.job_cortex") as mock_job_cortex:
            mock_job_cortex.kiq = mock_kiq
            result = await job_extract.original_func("event-1", "run-1", "ws-1")

    mock_kiq.assert_awaited_once_with("event-1", "run-1", "ws-1")
    assert result["status"] == "routed_to_cortex"
    assert result["event_id"] == "event-1"


# ── Test 4: Empty event → no crystal chunks ──────────────────────────────────


@pytest.mark.asyncio
async def test_cortex_pipeline_empty_event_no_crystal_chunks() -> None:
    """Empty text event → CortexChunker returns 1 empty chunk; FakeLLM all-zero → not crystal."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    event = _make_event("")  # empty text
    run = _make_run()
    mock_chunk = _make_chunk_obj()

    mock_factory, _ = _make_mock_session_factory()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=mock_chunk)
    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock(return_value=MagicMock())

    original_rls = worker_tasks._set_workspace_context

    async def noop_rls(session, wid):
        pass

    worker_tasks._set_workspace_context = noop_rls  # type: ignore[assignment]

    try:
        with (
            patch("alayaos_core.worker.tasks.Settings", return_value=_mock_settings(threshold=0.9)),
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
            patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
            patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
            patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        ):
            result = await worker_tasks.job_cortex.original_func(event_id, run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original_rls  # type: ignore[assignment]

    assert result["chunks_crystal"] == 0
    assert result["status"] == "cortex_complete"


# ── Test 5: event not found → skipped ───────────────────────────────────────


@pytest.mark.asyncio
async def test_cortex_pipeline_skips_when_event_not_found() -> None:
    """job_cortex returns skipped when event lookup returns None."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    mock_factory, _ = _make_mock_session_factory()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=None)  # not found
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=_make_run())

    original_rls = worker_tasks._set_workspace_context

    async def noop_rls(session, wid):
        pass

    worker_tasks._set_workspace_context = noop_rls  # type: ignore[assignment]

    try:
        with (
            patch("alayaos_core.worker.tasks.Settings", return_value=_mock_settings()),
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
            patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
            patch("alayaos_core.repositories.chunk.ChunkRepository"),
            patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository"),
        ):
            result = await worker_tasks.job_cortex.original_func(event_id, run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original_rls  # type: ignore[assignment]

    assert result["status"] == "skipped"
    assert result["reason"] == "event or run not found"
