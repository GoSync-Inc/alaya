"""TaskIQ task definitions for the three-job extraction pipeline."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.worker.broker import broker


async def _set_workspace_context(session: AsyncSession, workspace_id: str) -> None:
    """Set RLS workspace context for the current transaction.

    asyncpg executes parameterized queries as prepared statements, and
    PostgreSQL rejects bind parameters inside SET commands.  We validate
    via uuid.UUID() to prevent injection, then interpolate directly.
    """
    validated_wid = str(uuid.UUID(workspace_id))
    await session.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))


def _session_factory():
    settings = Settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


@broker.task(timeout=120, retry_on_error=True, max_retries=3)
async def job_extract(event_id: str, extraction_run_id: str, workspace_id: str) -> dict:
    """Job 1: Extract — preprocess + LLM extraction + store raw result."""
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.pipeline import run_extraction
    from alayaos_core.extraction.preprocessor import Preprocessor
    from alayaos_core.llm.fake import FakeLLMAdapter
    from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES

    settings = Settings()
    # Use real adapter in production, fake for dev/test
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.ANTHROPIC_MODEL)
    else:
        llm = FakeLLMAdapter()

    preprocessor = Preprocessor()
    extractor = Extractor(llm)

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        result = await run_extraction(
            event_id=uuid.UUID(event_id),
            run_id=uuid.UUID(extraction_run_id),
            session=session,
            llm=llm,
            preprocessor=preprocessor,
            extractor=extractor,
            entity_types=[dict(et) for et in CORE_ENTITY_TYPES],
            predicates=[dict(p) for p in CORE_PREDICATES],
        )

    if result:
        await job_write.kiq(extraction_run_id, workspace_id)

    return {"event_id": event_id, "extraction_run_id": extraction_run_id, "status": "extracted"}


@broker.task(timeout=60, retry_on_error=True, max_retries=3)
async def job_write(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 2: Write — resolve entities + atomic write."""
    from alayaos_core.extraction.pipeline import run_write
    from alayaos_core.llm.fake import FakeLLMAdapter

    settings = Settings()
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.ANTHROPIC_MODEL)
    else:
        llm = FakeLLMAdapter()

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        counters = await run_write(
            run_id=uuid.UUID(extraction_run_id),
            session=session,
            llm=llm,
        )

    if counters:
        await job_enrich.kiq(extraction_run_id, workspace_id)

    return {"extraction_run_id": extraction_run_id, "status": "written"}


@broker.task(timeout=120, retry_on_error=True, max_retries=3)
async def job_cortex(event_id: str, extraction_run_id: str, workspace_id: str) -> dict:
    """Cortex stage: sanitize event → chunk → classify each chunk → write L0Chunks → trace → enqueue crystallizer per crystal chunk."""
    from alayaos_core.extraction.cortex.chunker import CortexChunker
    from alayaos_core.extraction.cortex.classifier import CortexClassifier
    from alayaos_core.extraction.sanitizer import sanitize
    from alayaos_core.repositories.chunk import ChunkRepository
    from alayaos_core.repositories.event import EventRepository
    from alayaos_core.repositories.extraction_run import ExtractionRunRepository
    from alayaos_core.repositories.pipeline_trace import PipelineTraceRepository

    settings = Settings()
    # Use Haiku for classification (cheap, fast)
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.CORTEX_CLASSIFIER_MODEL)
    else:
        from alayaos_core.llm.fake import FakeLLMAdapter

        llm = FakeLLMAdapter()

    chunker = CortexChunker(max_chunk_tokens=settings.CORTEX_MAX_CHUNK_TOKENS)
    classifier = CortexClassifier(
        llm=llm,
        crystal_threshold=settings.CORTEX_CRYSTAL_THRESHOLD,
        truncation_tokens=settings.CORTEX_TRUNCATION_TOKENS,
    )

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)

        event_repo = EventRepository(session, uuid.UUID(workspace_id))
        run_repo = ExtractionRunRepository(session, uuid.UUID(workspace_id))
        chunk_repo = ChunkRepository(session, uuid.UUID(workspace_id))
        trace_repo = PipelineTraceRepository(session, uuid.UUID(workspace_id))

        event = await event_repo.get_by_id(uuid.UUID(event_id))
        run = await run_repo.get_by_id(uuid.UUID(extraction_run_id))
        if not event or not run:
            return {"status": "skipped", "reason": "event or run not found"}

        # Sanitize
        text = event.raw_text or event.content.get("text", "")
        text = sanitize(text)

        # Chunk
        raw_chunks = chunker.chunk(text, event.source_type, event.source_id)

        # Classify each chunk + write to DB
        total_cortex_cost = 0.0
        chunks_crystal = 0
        chunks_skipped = 0
        verification_changes = 0

        for rc in raw_chunks:
            scores, changed, usage = await classifier.classify_and_verify(rc)
            total_cortex_cost += usage.cost_usd
            if changed:
                verification_changes += 1

            is_crystal = classifier.is_crystal(scores)
            primary = classifier.primary_domain(scores)

            chunk = await chunk_repo.create(
                workspace_id=uuid.UUID(workspace_id),
                event_id=event.id,
                chunk_index=rc.index,
                chunk_total=rc.total,
                text=rc.text,
                token_count=rc.token_count,
                source_type=rc.source_type,
                source_id=rc.source_id,
                domain_scores=scores.model_dump(),
                primary_domain=primary,
                is_crystal=is_crystal,
                classification_model=settings.CORTEX_CLASSIFIER_MODEL,
                extraction_run_id=run.id,
            )

            # Update classification flags
            chunk.classification_verified = True
            chunk.verification_changed = changed

            if is_crystal:
                chunks_crystal += 1
            else:
                chunks_skipped += 1

            # Write pipeline trace
            await trace_repo.create(
                workspace_id=uuid.UUID(workspace_id),
                event_id=event.id,
                stage="cortex",
                decision="classified" if is_crystal else "skipped",
                reason=f"primary={primary}, crystal={is_crystal}",
                details={"scores": scores.model_dump(), "changed": changed},
                tokens_used=usage.tokens_in + usage.tokens_out,
                cost_usd=usage.cost_usd,
                extraction_run_id=run.id,
            )

        # Update extraction run counters
        run.chunks_total = len(raw_chunks)
        run.chunks_crystal = chunks_crystal
        run.chunks_skipped = chunks_skipped
        run.cortex_cost_usd = total_cortex_cost
        run.verification_changes = verification_changes
        await session.flush()

    # Enqueue job_crystallize per crystal chunk (outside the session)
    # This will be implemented in Sprint 3 — for now just log
    return {
        "event_id": event_id,
        "extraction_run_id": extraction_run_id,
        "chunks_total": len(raw_chunks),
        "chunks_crystal": chunks_crystal,
        "status": "cortex_complete",
    }


@broker.task(timeout=60, retry_on_error=True, max_retries=2)
async def job_enrich(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 3: Enrich — embedding stub (deferred to Run 3)."""
    from alayaos_core.extraction.pipeline import run_enrich

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        await run_enrich(uuid.UUID(extraction_run_id), session)

    return {"extraction_run_id": extraction_run_id, "status": "enriched"}
