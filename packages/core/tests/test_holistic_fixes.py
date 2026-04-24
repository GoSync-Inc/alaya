"""Tests for holistic review fixes: zero-crystal event marking, cortex idempotency, Redis in crystallize."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Fix 4: Zero-crystal events must be marked is_extracted=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_cortex_zero_crystal_marks_event_extracted():
    """job_cortex marks event.is_extracted=True when no crystal chunks exist."""
    from alayaos_core.worker import tasks as tasks_mod

    ws_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    # Event mock
    mock_event = MagicMock()
    mock_event.id = uuid.UUID(event_id)
    mock_event.raw_text = "boring noise"
    mock_event.content = {}
    mock_event.source_type = "slack"
    mock_event.source_id = "C1"
    mock_event.is_extracted = False

    # Run mock (not yet completed)
    mock_run = MagicMock()
    mock_run.id = uuid.UUID(run_id)
    mock_run.status = "pending"
    mock_run.chunks_total = 0
    mock_run.chunks_crystal = 0
    mock_run.chunks_skipped = 0
    mock_run.cortex_cost_usd = 0.0
    mock_run.verification_changes = 0

    # Repos — module-level names used through local imports
    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=mock_event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=mock_event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    mock_chunk_repo.list_crystal = AsyncMock(return_value=[])  # no crystal chunks

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    # Chunker returns one non-crystal chunk
    mock_raw_chunk = MagicMock()
    mock_raw_chunk.index = 0
    mock_raw_chunk.total = 1
    mock_raw_chunk.text = "boring noise"
    mock_raw_chunk.token_count = 5
    mock_raw_chunk.source_type = "slack"
    mock_raw_chunk.source_id = "C1"

    mock_chunker = MagicMock()
    mock_chunker.chunk = MagicMock(return_value=[mock_raw_chunk])

    # Classifier: non-crystal
    mock_scores = MagicMock()
    mock_scores.model_dump = MagicMock(return_value={})
    mock_usage = MagicMock()
    mock_usage.cost_usd = 0.001
    mock_usage.tokens_in = 10
    mock_usage.tokens_out = 5

    mock_classifier = MagicMock()
    mock_classifier.classify_and_verify = AsyncMock(return_value=(mock_scores, False, mock_usage))
    mock_classifier.is_crystal = MagicMock(return_value=False)
    mock_classifier.primary_domain = MagicMock(return_value="noise")

    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session_ctx)

    mock_settings = MagicMock()
    mock_settings.ANTHROPIC_API_KEY = MagicMock()
    mock_settings.ANTHROPIC_API_KEY.get_secret_value = MagicMock(return_value="")
    mock_settings.CORTEX_MAX_CHUNK_TOKENS = 512
    mock_settings.CORTEX_CRYSTAL_THRESHOLD = 0.6
    mock_settings.CORTEX_TRUNCATION_TOKENS = 256
    mock_settings.CORTEX_CLASSIFIER_MODEL = "claude-haiku"
    mock_settings.FEATURE_FLAG_USE_CORTEX = True

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        # Patch at the source module, since tasks.py imports these locally
        patch("alayaos_core.extraction.cortex.chunker.CortexChunker", return_value=mock_chunker),
        patch("alayaos_core.extraction.cortex.classifier.CortexClassifier", return_value=mock_classifier),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.extraction.pipeline.should_extract", new=AsyncMock(return_value=True)),
        patch("alayaos_core.extraction.sanitizer.sanitize", return_value="boring noise"),
    ):
        await tasks_mod.job_cortex(event_id, run_id, ws_id)

    # is_extracted must have been set to True on the event
    assert mock_event.is_extracted is True, "event.is_extracted should be True after zero-crystal run"
    # run must be marked completed
    mock_run_repo.update_status.assert_called_with(uuid.UUID(run_id), "completed")


# ---------------------------------------------------------------------------
# Fix 5: job_cortex skips on cortex_complete status (idempotency)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_cortex_skips_when_cortex_complete():
    """job_cortex returns skipped when run.status is already 'cortex_complete'."""
    from alayaos_core.worker import tasks as tasks_mod

    ws_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    mock_event = MagicMock()
    mock_event.id = uuid.UUID(event_id)

    mock_run = MagicMock()
    mock_run.id = uuid.UUID(run_id)
    mock_run.status = "cortex_complete"  # already processed

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_id = AsyncMock(return_value=mock_event)
    mock_event_repo.get_by_id_unfiltered = AsyncMock(return_value=mock_event)

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)

    mock_session = AsyncMock()
    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session_ctx)

    mock_settings = MagicMock()
    mock_settings.ANTHROPIC_API_KEY = MagicMock()
    mock_settings.ANTHROPIC_API_KEY.get_secret_value = MagicMock(return_value="")
    mock_settings.CORTEX_MAX_CHUNK_TOKENS = 512
    mock_settings.CORTEX_CRYSTAL_THRESHOLD = 0.6
    mock_settings.CORTEX_TRUNCATION_TOKENS = 256
    mock_settings.CORTEX_CLASSIFIER_MODEL = "claude-haiku"

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.event.EventRepository", return_value=mock_event_repo),
        patch("alayaos_core.worker.tasks.ExtractionRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=AsyncMock()),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=AsyncMock()),
    ):
        result = await tasks_mod.job_cortex(event_id, run_id, ws_id)

    assert result["status"] == "skipped"
    assert result["reason"] == "already processed"


# ---------------------------------------------------------------------------
# Fix 7: job_crystallize wires Redis for EntityCacheService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_crystallize_creates_redis_for_entity_cache():
    """job_crystallize creates a Redis client and passes it to EntityCacheService."""
    from alayaos_core.worker import tasks as tasks_mod

    ws_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    captured_redis = []

    def capture_entity_cache(redis=None):
        captured_redis.append(redis)
        return MagicMock()

    mock_settings = MagicMock()
    mock_settings.ANTHROPIC_API_KEY = MagicMock()
    mock_settings.ANTHROPIC_API_KEY.get_secret_value = MagicMock(return_value="")
    mock_settings.REDIS_URL = SecretStr("redis://localhost:6379")
    mock_settings.CRYSTALLIZER_MODEL = "claude-3-5-sonnet"
    mock_settings.CRYSTALLIZER_CONFIDENCE_HIGH = 0.8
    mock_settings.CRYSTALLIZER_CONFIDENCE_LOW = 0.5

    # Mock chunk in 'classified' stage
    mock_chunk = MagicMock()
    mock_chunk.id = uuid.UUID(chunk_id)
    mock_chunk.processing_stage = "classified"
    mock_chunk.text = "Important update: deadline moved"
    mock_chunk.event_id = uuid.uuid4()

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.get_by_id = AsyncMock(return_value=None)
    mock_chunk_repo.get_by_id_unfiltered = AsyncMock(return_value=mock_chunk)
    mock_chunk_repo.update_processing_stage = AsyncMock()
    mock_chunk_repo.list_by_event = AsyncMock(return_value=[])

    mock_run = MagicMock()
    mock_run.id = uuid.UUID(run_id)
    mock_run.raw_extraction = None
    mock_run.crystallizer_cost_usd = 0.0

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock()

    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    # For sa_select().with_for_update() — mock execute returning run
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none = MagicMock(return_value=mock_run)
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session_ctx)

    # Mock extraction result
    mock_extraction_result = MagicMock()
    mock_extraction_result.entities = []
    mock_extraction_result.relations = []
    mock_extraction_result.claims = []
    mock_extraction_result.model_dump = MagicMock(return_value={"entities": [], "relations": [], "claims": []})

    mock_usage = MagicMock()
    mock_usage.cost_usd = 0.001
    mock_usage.tokens_in = 10
    mock_usage.tokens_out = 5

    mock_extractor = MagicMock()
    mock_extractor.extract = AsyncMock(return_value=(mock_extraction_result, mock_usage))
    mock_extractor._build_prompt = MagicMock(return_value="sys prompt")

    mock_verifier = MagicMock()
    mock_verifier.verify = AsyncMock(return_value=(mock_extraction_result, False, mock_usage))

    mock_redis_client = AsyncMock()
    mock_redis_client.aclose = AsyncMock()

    mock_aioredis_mod = MagicMock()
    mock_aioredis_mod.from_url = MagicMock(return_value=mock_redis_client)

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.repositories.chunk.ChunkRepository", return_value=mock_chunk_repo),
        patch("alayaos_core.repositories.pipeline_trace.PipelineTraceRepository", return_value=mock_trace_repo),
        patch("alayaos_core.extraction.crystallizer.extractor.CrystallizerExtractor", return_value=mock_extractor),
        patch("alayaos_core.extraction.crystallizer.verifier.CrystallizerVerifier", return_value=mock_verifier),
        patch(
            "alayaos_core.extraction.crystallizer.extractor.apply_confidence_tiers", return_value=mock_extraction_result
        ),
        # EntityCacheService is imported at module level in tasks.py, so patch there
        patch("alayaos_core.worker.tasks.EntityCacheService", side_effect=capture_entity_cache),
        patch("alayaos_core.worker.tasks.aioredis", mock_aioredis_mod),
        patch("alayaos_core.worker.tasks.job_write") as mock_job_write,
    ):
        mock_job_write.kiq = AsyncMock()
        await tasks_mod.job_crystallize(chunk_id, run_id, ws_id)

    # Redis must have been passed (not None) to EntityCacheService
    assert captured_redis, "EntityCacheService was not called"
    assert captured_redis[0] is not None, "EntityCacheService should receive a real Redis client, not None"


# ---------------------------------------------------------------------------
# Fix 6: broker.py exports a TaskiqScheduler
# ---------------------------------------------------------------------------


def test_broker_module_exports_scheduler():
    """broker.py must export a TaskiqScheduler instance named 'scheduler'."""
    from alayaos_core.worker import broker as broker_mod

    assert hasattr(broker_mod, "scheduler"), "broker module must export 'scheduler'"
    from taskiq import TaskiqScheduler

    assert isinstance(broker_mod.scheduler, TaskiqScheduler), "broker.scheduler must be a TaskiqScheduler instance"


def test_job_check_integrator_has_schedule_label():
    """job_check_integrator task must carry a 'schedule' label for cron execution."""
    from alayaos_core.worker.tasks import job_check_integrator

    # TaskIQ stores labels via broker's task registry or task attributes
    # The schedule is stored as a label on the task definition
    task_labels = getattr(job_check_integrator, "labels", {})
    assert "schedule" in task_labels, "job_check_integrator must have a 'schedule' label for TaskIQ periodic execution"
    schedule_val = task_labels["schedule"]
    assert isinstance(schedule_val, list) and len(schedule_val) > 0, "schedule label must be a non-empty list"
    assert "cron" in schedule_val[0], "schedule entry must contain a 'cron' key"
