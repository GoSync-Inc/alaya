"""End-to-end pipeline tests: Cortex → Crystallizer → Writer (mock-based).

These tests verify the full pipeline wiring using FakeLLMAdapter and
mocked repositories/session. They do not require a real database.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_event(
    event_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    raw_text: str = "Alice is the owner of Project Phoenix. Deadline is April 15.",
) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.access_level = "public"
    event.source_type = "slack"
    event.source_id = "C123/T456"
    event.content = {"text": raw_text}
    event.raw_text = raw_text
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
    run.chunks_total = 0
    run.chunks_crystal = 0
    run.chunks_skipped = 0
    run.cortex_cost_usd = 0.0
    run.crystallizer_cost_usd = 0.0
    run.verification_changes = 0
    return run


def _make_chunk(
    chunk_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    is_crystal: bool = True,
    processing_stage: str = "classified",
) -> MagicMock:
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.event_id = event_id or uuid.uuid4()
    chunk.is_crystal = is_crystal
    chunk.processing_stage = processing_stage
    chunk.text = "Alice is the owner of Project Phoenix."
    return chunk


def _make_mock_session() -> tuple[MagicMock, MagicMock]:
    """Return (mock_session, mock_factory)."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value = mock_session
    return mock_session, mock_factory


@pytest.mark.asyncio
async def test_full_pipeline_cortex_to_writer():
    """End-to-end: ingest event → job_cortex creates chunks → job_crystallize is enqueued."""
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id)
    run = _make_run(run_id=run_id, event_id=event_id)
    crystal_chunk = _make_chunk(chunk_id=chunk_id, event_id=event_id, is_crystal=True)

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=crystal_chunk)
    mock_chunk_repo.list_crystal = AsyncMock(return_value=[crystal_chunk])

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    _, mock_factory = _make_mock_session()

    mock_job_crystallize = AsyncMock()
    mock_job_crystallize.kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.repositories.extraction_run.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.worker.tasks.job_crystallize", mock_job_crystallize),
        patch("alayaos_core.extraction.pipeline.should_extract", new=AsyncMock(return_value=True)),
    ):
        from alayaos_core.worker.tasks import job_cortex

        result = await job_cortex(str(event_id), str(run_id), str(workspace_id))

    assert result["status"] == "cortex_complete"
    assert result["event_id"] == str(event_id)
    # job_crystallize.kiq should be called for each crystal chunk
    mock_job_crystallize.kiq.assert_called_once_with(str(chunk_id), str(run_id), str(workspace_id))


@pytest.mark.asyncio
async def test_full_pipeline_job_cortex_creates_chunks():
    """Cortex stage creates L0Chunks for each text segment from CortexChunker."""
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    event = _make_event(
        event_id=event_id,
        workspace_id=workspace_id,
        raw_text="Alice leads the team.\n\nDeadline is next week. Blockers: none.",
    )
    run = _make_run(run_id=run_id, event_id=event_id)
    crystal_chunk = _make_chunk(chunk_id=chunk_id, event_id=event_id, is_crystal=True)

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=crystal_chunk)
    mock_chunk_repo.list_crystal = AsyncMock(return_value=[crystal_chunk])

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    _, mock_factory = _make_mock_session()

    mock_job_crystallize = AsyncMock()
    mock_job_crystallize.kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.repositories.extraction_run.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.worker.tasks.job_crystallize", mock_job_crystallize),
        patch("alayaos_core.extraction.pipeline.should_extract", new=AsyncMock(return_value=True)),
    ):
        from alayaos_core.worker.tasks import job_cortex

        result = await job_cortex(str(event_id), str(run_id), str(workspace_id))

    # Chunk repo create was called at least once (one chunk per text segment)
    assert mock_chunk_repo.create.called
    assert result["chunks_total"] >= 1


@pytest.mark.asyncio
async def test_full_pipeline_no_crystal_chunks_completes_run():
    """If no crystal chunks exist, cortex marks run completed without enqueuing crystallizer."""
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    event = _make_event(event_id=event_id, workspace_id=workspace_id, raw_text="okay thanks bye")
    run = _make_run(run_id=run_id, event_id=event_id)
    # Non-crystal chunk
    skipped_chunk = _make_chunk(chunk_id=chunk_id, event_id=event_id, is_crystal=False)

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run)
    mock_run_repo.update_status = AsyncMock()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=skipped_chunk)
    # No crystal chunks
    mock_chunk_repo.list_crystal = AsyncMock(return_value=[])

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    _, mock_factory = _make_mock_session()

    mock_job_crystallize = AsyncMock()
    mock_job_crystallize.kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.repositories.extraction_run.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.worker.tasks.job_crystallize", mock_job_crystallize),
        patch("alayaos_core.extraction.pipeline.should_extract", new=AsyncMock(return_value=True)),
    ):
        from alayaos_core.worker.tasks import job_cortex

        result = await job_cortex(str(event_id), str(run_id), str(workspace_id))

    # job_crystallize should NOT have been enqueued
    mock_job_crystallize.kiq.assert_not_called()
    assert result["chunks_crystal"] == 0


@pytest.mark.asyncio
async def test_full_pipeline_job_write_triggered_after_crystallizer():
    """After all crystal chunks are extracted, job_write is triggered."""
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    # Chunk in 'classified' stage → crystallizer processes it
    chunk = _make_chunk(chunk_id=chunk_id, event_id=event_id, is_crystal=True, processing_stage="classified")

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.get_by_id = AsyncMock(return_value=chunk)
    mock_chunk_repo.update_processing_stage = AsyncMock()
    # After update, all crystal chunks are 'extracted'
    extracted_chunk = _make_chunk(chunk_id=chunk_id, event_id=event_id, is_crystal=True, processing_stage="extracted")
    mock_chunk_repo.list_by_event = AsyncMock(return_value=[extracted_chunk])

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.raw_extraction = {"entities": [], "relations": [], "claims": []}
    mock_run.crystallizer_cost_usd = 0.0

    mock_session_result = MagicMock()
    mock_session_result.scalar_one_or_none = MagicMock(return_value=mock_run)

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_session_result)
    mock_session.flush = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    mock_job_write = AsyncMock()
    mock_job_write.kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.worker.tasks.job_write", mock_job_write),
        patch("alayaos_core.extraction.crystallizer.extractor.CrystallizerExtractor") as mock_extractor_cls,
        patch("alayaos_core.extraction.crystallizer.verifier.CrystallizerVerifier") as mock_verifier_cls,
        patch("alayaos_core.worker.tasks.EntityCacheService"),
    ):
        from alayaos_core.extraction.schemas import ExtractionResult
        from alayaos_core.llm.interface import LLMUsage

        empty_result = ExtractionResult(entities=[], relations=[], claims=[])
        mock_usage = LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.0)

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=(empty_result, mock_usage))
        mock_extractor._build_prompt = MagicMock(return_value="system prompt")
        mock_extractor_cls.return_value = mock_extractor

        mock_verifier = AsyncMock()
        mock_verifier.verify = AsyncMock(return_value=(empty_result, False, mock_usage))
        mock_verifier_cls.return_value = mock_verifier

        from alayaos_core.worker.tasks import job_crystallize

        result = await job_crystallize(str(chunk_id), str(run_id), str(workspace_id))

    assert result["status"] == "extracted"
    # job_write should have been triggered since all crystal chunks are extracted
    mock_job_write.kiq.assert_called_once_with(str(run_id), str(workspace_id))
