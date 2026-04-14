"""Tests for job_cortex, job_crystallize, and job_write failure handling."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_session():
    """Create a mock async session context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()
    return mock_session


@pytest.mark.asyncio
async def test_job_write_marks_run_failed_on_validation_error():
    """job_write catches ValidationError, marks run as failed, then re-raises."""
    from pydantic import BaseModel, ValidationError

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Build a real ValidationError from Pydantic
    validation_error: ValidationError
    try:

        class _M(BaseModel):
            x: int

        _M(x="not_an_int")  # type: ignore[arg-type]
        pytest.fail("Expected ValidationError was not raised")
    except ValidationError as ve:
        validation_error = ve

    main_session = _make_mock_session()
    mock_factory = MagicMock(return_value=main_session)
    mock_mark_failed = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks._mark_extraction_run_failed", mock_mark_failed),
        patch("alayaos_core.extraction.pipeline.run_write", side_effect=validation_error),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_write

        with pytest.raises(ValidationError):
            await job_write.original_func(str(run_id), str(ws_id))

    mock_mark_failed.assert_awaited_once()
    call_kwargs = mock_mark_failed.call_args
    # Positional args: factory, workspace_id, run_id=..., error_message=..., error_detail=...
    assert call_kwargs.kwargs["run_id"] == run_id
    assert call_kwargs.kwargs["error_message"] is not None
    error_detail = call_kwargs.kwargs["error_detail"]
    assert error_detail["stage"] == "write"
    assert error_detail["type"] == "ValidationError"


@pytest.mark.asyncio
async def test_job_crystallize_marks_run_failed_on_llm_error():
    """job_crystallize catches anthropic.APIStatusError, marks run as failed, then re-raises."""
    import anthropic

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    api_error = anthropic.APIStatusError(
        message="service overloaded",
        response=MagicMock(status_code=529, headers={}),
        body={"error": {"message": "service overloaded"}},
    )

    # Mock chunk
    mock_chunk = MagicMock()
    mock_chunk.processing_stage = "classified"
    mock_chunk.event_id = uuid.uuid4()
    mock_chunk.id = uuid.uuid4()
    mock_chunk.text = "some text"

    # Mock run row (returned by FOR UPDATE select)
    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.raw_extraction = None
    mock_run.crystallizer_cost_usd = 0.0

    main_session = _make_mock_session()
    # session.execute is called for the FOR UPDATE select → return mock_run
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=mock_run)
    main_session.execute = AsyncMock(return_value=scalar_result)

    mock_factory = MagicMock(return_value=main_session)
    mock_mark_failed = AsyncMock()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.get_by_id = AsyncMock(return_value=mock_chunk)
    mock_chunk_repo.update_processing_stage = AsyncMock()

    mock_extractor = AsyncMock()
    mock_extractor.extract = AsyncMock(side_effect=api_error)
    mock_extractor._build_prompt = MagicMock(return_value="prompt")

    mock_verifier = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks._mark_extraction_run_failed", mock_mark_failed),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=AsyncMock()),
        patch("alayaos_core.worker.tasks.EntityCacheService", return_value=MagicMock()),
        patch(
            "alayaos_core.extraction.crystallizer.extractor.CrystallizerExtractor",
            return_value=mock_extractor,
        ),
        patch(
            "alayaos_core.extraction.crystallizer.verifier.CrystallizerVerifier",
            return_value=mock_verifier,
        ),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_crystallize

        with pytest.raises(anthropic.APIStatusError):
            await job_crystallize.original_func(str(chunk_id), str(run_id), str(ws_id))

    mock_mark_failed.assert_awaited_once()
    call_kwargs = mock_mark_failed.call_args
    assert call_kwargs.kwargs["run_id"] == run_id
    assert call_kwargs.kwargs["error_message"] is not None
    error_detail = call_kwargs.kwargs["error_detail"]
    assert error_detail["stage"] == "crystallize"
    assert error_detail["type"] == "APIStatusError"


@pytest.mark.asyncio
async def test_job_cortex_marks_run_failed_on_exception():
    """job_cortex catches an exception from the cortex stage, marks run as failed, then re-raises."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    event_id = uuid.uuid4()

    cortex_error = RuntimeError("chunker exploded")

    main_session = _make_mock_session()
    mock_factory = MagicMock(return_value=main_session)
    mock_mark_failed = AsyncMock()

    mock_event = object()
    mock_run = MagicMock()
    mock_run.status = "pending"
    mock_run.id = run_id

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=mock_event)
    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock(side_effect=cortex_error)

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks._mark_extraction_run_failed", mock_mark_failed),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.extraction.pipeline.should_extract", new=AsyncMock(return_value=True)),
        patch("alayaos_core.extraction.cortex.chunker.CortexChunker", return_value=MagicMock()),
        patch("alayaos_core.extraction.cortex.classifier.CortexClassifier", return_value=AsyncMock()),
    ):
        from alayaos_core.worker.tasks import job_cortex

        with pytest.raises(RuntimeError):
            await job_cortex.original_func(str(event_id), str(run_id), str(ws_id))

    mock_mark_failed.assert_awaited_once()
    call_kwargs = mock_mark_failed.call_args
    assert call_kwargs.kwargs["run_id"] == run_id
    assert call_kwargs.kwargs["error_message"] is not None
    error_detail = call_kwargs.kwargs["error_detail"]
    assert error_detail["stage"] == "cortex"
    assert error_detail["type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_job_extract_marks_run_failed_on_exception():
    """job_extract (legacy non-Cortex path) catches exception from run_extraction, marks run as failed, then re-raises."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    event_id = uuid.uuid4()

    extraction_error = RuntimeError("legacy extractor exploded")

    main_session = _make_mock_session()
    mock_factory = MagicMock(return_value=main_session)
    mock_mark_failed = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks._mark_extraction_run_failed", mock_mark_failed),
        patch("alayaos_core.extraction.pipeline.run_extraction", side_effect=extraction_error),
        patch("alayaos_core.worker.tasks.Settings") as mock_settings_cls,
    ):
        mock_settings = MagicMock()
        mock_settings.FEATURE_FLAG_USE_CORTEX = False
        mock_settings.ANTHROPIC_API_KEY.get_secret_value.return_value = ""
        mock_settings_cls.return_value = mock_settings

        from alayaos_core.worker.tasks import job_extract

        with pytest.raises(RuntimeError):
            await job_extract.original_func(str(event_id), str(run_id), str(ws_id))

    mock_mark_failed.assert_awaited_once()
    call_kwargs = mock_mark_failed.call_args
    assert call_kwargs.kwargs["run_id"] == run_id
    assert call_kwargs.kwargs["error_message"] is not None
    error_detail = call_kwargs.kwargs["error_detail"]
    assert error_detail["stage"] == "extract"
    assert error_detail["type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_mark_failed_persists_status_and_error_fields():
    """mark_failed transitions run to failed with all expected fields set."""
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.models.extraction_run import ExtractionRun
    from alayaos_core.repositories.extraction_run import ExtractionRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    mock_run = MagicMock(spec=ExtractionRun)
    mock_run.id = run_id
    mock_run.status = "extracting"
    mock_run.error_message = None
    mock_run.error_detail = {}
    mock_run.completed_at = None

    session = AsyncMock()
    session.flush = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run
    session.execute = AsyncMock(return_value=mock_result)

    repo = ExtractionRunRepository(session, ws_id)
    await repo.mark_failed(
        run_id=run_id,
        error_message="test error",
        error_detail={"stage": "write", "type": "ValidationError"},
    )

    assert mock_run.status == "failed"
    assert mock_run.error_message == "test error"
    assert mock_run.error_detail == {"stage": "write", "type": "ValidationError"}
    assert mock_run.completed_at is not None
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_mark_failed_is_noop_on_terminal_status():
    """mark_failed is a no-op when the run is already in a terminal state."""
    from unittest.mock import AsyncMock, MagicMock

    from alayaos_core.models.extraction_run import ExtractionRun
    from alayaos_core.repositories.extraction_run import ExtractionRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    mock_run = MagicMock(spec=ExtractionRun)
    mock_run.id = run_id
    mock_run.status = "completed"
    mock_run.error_message = None
    mock_run.completed_at = None

    session = AsyncMock()
    session.flush = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run
    session.execute = AsyncMock(return_value=mock_result)

    repo = ExtractionRunRepository(session, ws_id)
    await repo.mark_failed(
        run_id=run_id,
        error_message="should be ignored",
        error_detail={"stage": "write"},
    )

    assert mock_run.status == "completed"
    assert mock_run.error_message is None
    assert mock_run.completed_at is None
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_recalc_usage_sums_traces():
    """recalc_usage issues an UPDATE that sums tokens_used and cost_usd from pipeline_traces."""
    from alayaos_core.repositories.extraction_run import ExtractionRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # First execute call is the SELECT EXISTS check — return a trace id so the guard passes.
    exists_result = MagicMock()
    exists_result.scalar_one_or_none.return_value = uuid.uuid4()  # trace exists
    update_result = MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[exists_result, update_result])

    repo = ExtractionRunRepository(session, ws_id)
    await repo.recalc_usage(run_id=run_id)

    assert session.execute.await_count == 2
    # Second call must be the UPDATE
    update_call_args = session.execute.call_args_list[1]
    stmt = update_call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "tokens_used" in compiled
    assert "cost_usd" in compiled
    # UUID may be rendered without dashes in compiled SQL
    assert run_id.hex in compiled


@pytest.mark.asyncio
async def test_recalc_usage_noop_when_no_traces():
    """recalc_usage must NOT issue an UPDATE when no pipeline_traces rows exist for the run.

    This guards the legacy non-Cortex path where tokens_in/cost_usd are written directly
    onto the ExtractionRun and no pipeline_traces rows are created. Without this guard,
    recalc_usage would overwrite correct values with 0.
    """
    from alayaos_core.repositories.extraction_run import ExtractionRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # The SELECT EXISTS check returns None — no traces exist.
    no_traces_result = MagicMock()
    no_traces_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=no_traces_result)

    repo = ExtractionRunRepository(session, ws_id)
    await repo.recalc_usage(run_id=run_id)

    # Only the existence check SELECT should have been issued — no UPDATE.
    session.execute.assert_awaited_once()
    call_args = session.execute.call_args
    stmt = call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # Must be a SELECT (existence check), not an UPDATE
    assert compiled.strip().upper().startswith("SELECT"), f"Expected SELECT, got: {compiled[:80]}"
    assert "UPDATE" not in compiled.upper()


@pytest.mark.asyncio
async def test_job_cortex_zero_crystal_path_calls_recalc_usage():
    """job_cortex must call recalc_usage when no crystal chunks are produced.

    Low-signal events (e.g. pure smalltalk) legitimately produce zero crystal chunks.
    The Haiku classifier still incurred real cost, so recalc_usage must be called so that
    tokens_in / cost_usd are persisted onto the extraction_run row.
    """
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    event_id = uuid.uuid4()

    mock_event = MagicMock()
    mock_event.is_extracted = False
    mock_event.raw_text = "hi"
    mock_event.content = {}
    mock_event.source_type = "slack"
    mock_event.source_id = "C123"
    mock_event.id = event_id

    mock_run = MagicMock()
    mock_run.status = "pending"
    mock_run.id = run_id

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock(return_value=mock_run)
    mock_run_repo.recalc_usage = AsyncMock()

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=mock_event)

    mock_chunk_repo = AsyncMock()
    # list_crystal returns empty list — zero crystal chunks
    mock_chunk_repo.list_crystal = AsyncMock(return_value=[])
    mock_chunk_repo.create = AsyncMock(return_value=MagicMock())

    mock_trace_repo = AsyncMock()

    # Chunker returns empty list → no chunks to classify → no crystal chunks
    mock_chunker = MagicMock()
    mock_chunker.chunk = MagicMock(return_value=[])

    mock_classifier = AsyncMock()

    main_session = _make_mock_session()
    mock_factory = MagicMock(return_value=main_session)

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks._mark_extraction_run_failed", AsyncMock()),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch(
            "alayaos_core.extraction.pipeline.should_extract",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "alayaos_core.extraction.cortex.chunker.CortexChunker",
            return_value=mock_chunker,
        ),
        patch(
            "alayaos_core.extraction.cortex.classifier.CortexClassifier",
            return_value=mock_classifier,
        ),
        patch("alayaos_core.extraction.sanitizer.sanitize", return_value="hi"),
    ):
        from alayaos_core.worker.tasks import job_cortex

        await job_cortex.original_func(str(event_id), str(run_id), str(ws_id))

    mock_run_repo.recalc_usage.assert_awaited_once_with(uuid.UUID(str(run_id)))
