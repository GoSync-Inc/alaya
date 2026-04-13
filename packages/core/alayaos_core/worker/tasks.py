"""TaskIQ task definitions for the three-job extraction pipeline."""

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.extraction.integrator.engine import IntegratorEngine
from alayaos_core.repositories.claim import ClaimRepository
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.integrator_run import IntegratorRunRepository
from alayaos_core.repositories.relation import RelationRepository
from alayaos_core.repositories.workspace import WorkspaceRepository
from alayaos_core.services.entity_cache import EntityCacheService
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


async def _mark_integrator_run_failed(
    factory,
    workspace_id: str,
    run_id: uuid.UUID,
    error_message: str,
) -> None:
    ws_uuid = uuid.UUID(workspace_id)
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        run_repo = IntegratorRunRepository(session, ws_uuid)
        await run_repo.update_status(run_id, "failed", error_message=error_message)


async def _create_integrator_run(
    factory,
    workspace_id: str,
    *,
    trigger: str,
    scope_description: str | None,
    llm_model: str | None,
) -> uuid.UUID:
    ws_uuid = uuid.UUID(workspace_id)
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        run_repo = IntegratorRunRepository(session, ws_uuid)
        run = await run_repo.create(
            workspace_id=ws_uuid,
            trigger=trigger,
            scope_description=scope_description,
            llm_model=llm_model,
        )
        return run.id


async def _reap_stuck_integrator_runs(factory, *, stuck_after_seconds: int) -> int:
    started_before = datetime.now(UTC) - timedelta(seconds=stuck_after_seconds)
    reason = f"stuck integrator run exceeded {stuck_after_seconds}s"
    workspace_ids: list[uuid.UUID] = []

    async with factory() as session:
        workspace_repo = WorkspaceRepository(session)
        cursor: str | None = None
        while True:
            workspaces, next_cursor, has_more = await workspace_repo.list(cursor=cursor, limit=200)
            workspace_ids.extend(workspace.id for workspace in workspaces)
            if not has_more:
                break
            cursor = next_cursor

    reaped = 0
    for workspace_id in workspace_ids:
        async with factory() as session, session.begin():
            workspace_id_str = str(workspace_id)
            await _set_workspace_context(session, workspace_id_str)
            run_repo = IntegratorRunRepository(session, workspace_id)
            reaped += await run_repo.mark_stale_running_failed(
                started_before=started_before,
                error_message=reason,
            )

    return reaped


@broker.task(timeout=120, retry_on_error=True, max_retries=3)
async def job_extract(event_id: str, extraction_run_id: str, workspace_id: str) -> dict:
    """Job 1: Extract — preprocess + LLM extraction + store raw result."""
    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.pipeline import run_extraction
    from alayaos_core.extraction.preprocessor import Preprocessor
    from alayaos_core.llm.fake import FakeLLMAdapter
    from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES

    settings = Settings()

    # Feature flag: route to Cortex pipeline when enabled
    if settings.FEATURE_FLAG_USE_CORTEX:
        await job_cortex.kiq(event_id, extraction_run_id, workspace_id)
        return {"event_id": event_id, "status": "routed_to_cortex"}

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

    # Connect to Redis for dirty-set push + entity cache invalidation
    import redis.asyncio as aioredis

    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL)

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        counters = await run_write(
            run_id=uuid.UUID(extraction_run_id),
            session=session,
            llm=llm,
            redis=redis_client,
        )

    if redis_client:
        await redis_client.aclose()

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

        # Idempotency: skip if already processed (completed or cortex_complete)
        if run.status in ("completed", "cortex_complete"):
            return {"status": "skipped", "reason": "already processed"}

        # Access-level gating (same as existing should_extract in pipeline.py)
        from alayaos_core.extraction.pipeline import should_extract

        if not await should_extract(event, run, run_repo, session):
            return {"status": "skipped", "reason": "access_level denied"}

        await run_repo.update_status(run.id, "extracting")

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

        # Update extraction run counters and status
        run.chunks_total = len(raw_chunks)
        run.chunks_crystal = chunks_crystal
        run.chunks_skipped = chunks_skipped
        run.cortex_cost_usd = total_cortex_cost
        run.verification_changes = verification_changes
        run.status = "cortex_complete"
        await session.flush()

    # Enqueue job_crystallize per crystal chunk (outside the session)
    crystal_chunk_ids = []
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        from alayaos_core.repositories.chunk import ChunkRepository

        chunk_repo = ChunkRepository(session, uuid.UUID(workspace_id))
        crystal_chunks = await chunk_repo.list_crystal(uuid.UUID(event_id))
        crystal_chunk_ids = [str(c.id) for c in crystal_chunks]

    if crystal_chunk_ids:
        for chunk_id in crystal_chunk_ids:
            await job_crystallize.kiq(chunk_id, extraction_run_id, workspace_id)
    else:
        # No crystal chunks — complete the run (nothing to extract)
        # Also mark event as extracted so it is not reprocessed on retry
        async with factory() as session, session.begin():
            await _set_workspace_context(session, workspace_id)
            run_repo = ExtractionRunRepository(session, uuid.UUID(workspace_id))
            await run_repo.update_status(uuid.UUID(extraction_run_id), "completed")
            event_repo = EventRepository(session, uuid.UUID(workspace_id))
            event = await event_repo.get_by_id(uuid.UUID(event_id))
            if event:
                event.is_extracted = True
                await session.flush()

    return {
        "event_id": event_id,
        "extraction_run_id": extraction_run_id,
        "chunks_total": len(raw_chunks),
        "chunks_crystal": chunks_crystal,
        "status": "cortex_complete",
    }


@broker.task(timeout=120, retry_on_error=True, max_retries=3)
async def job_crystallize(chunk_id: str, extraction_run_id: str, workspace_id: str) -> dict:
    """Crystallizer stage: extract from crystal chunk → verify → update chunk stage → trace → enqueue job_write."""
    from alayaos_core.extraction.crystallizer.extractor import CrystallizerExtractor, apply_confidence_tiers
    from alayaos_core.extraction.crystallizer.verifier import CrystallizerVerifier
    from alayaos_core.llm.fake import FakeLLMAdapter
    from alayaos_core.repositories.chunk import ChunkRepository
    from alayaos_core.repositories.pipeline_trace import PipelineTraceRepository
    from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES
    # EntityCacheService is already imported at module level — no local import needed

    settings = Settings()

    # Use real LLM adapter if key is available
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.CRYSTALLIZER_MODEL)
    else:
        llm = FakeLLMAdapter()

    # Wire Redis so EntityCacheService can use the shared entity cache
    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL)

    entity_cache = EntityCacheService(redis=redis_client)

    extractor = CrystallizerExtractor(llm=llm, entity_cache=entity_cache)
    verifier = CrystallizerVerifier(llm=llm)

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)

        chunk_repo = ChunkRepository(session, uuid.UUID(workspace_id))
        trace_repo = PipelineTraceRepository(session, uuid.UUID(workspace_id))

        chunk = await chunk_repo.get_by_id(uuid.UUID(chunk_id))
        if chunk is None:
            return {"status": "skipped", "reason": "chunk not found"}

        # Idempotency: skip if not in 'classified' stage
        if chunk.processing_stage != "classified":
            return {"status": "skipped", "reason": f"stage={chunk.processing_stage}"}

        # Lock extraction run row to serialize concurrent chunk tasks
        from sqlalchemy import select as sa_select

        from alayaos_core.models.extraction_run import ExtractionRun

        stmt = sa_select(ExtractionRun).where(ExtractionRun.id == uuid.UUID(extraction_run_id)).with_for_update()
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return {"status": "skipped", "reason": "run not found"}

        # Update chunk to 'extracting'
        await chunk_repo.update_processing_stage(chunk.id, "extracting")

        # Extract
        entity_types = [dict(et) for et in CORE_ENTITY_TYPES]
        predicates = [dict(p) for p in CORE_PREDICATES]
        extraction_result, usage_extract = await extractor.extract(
            chunk=chunk,
            entity_types=entity_types,
            predicates=predicates,
            workspace_id=uuid.UUID(workspace_id),
        )

        # Build system prompt for verifier (same prompt for cache hit)
        system_prompt = extractor._build_prompt(entity_types, predicates, [], chunk)

        # Verify
        verified_result, verification_changed, usage_verify = await verifier.verify(
            chunk_text=chunk.text,
            system_prompt=system_prompt,
            initial_result=extraction_result,
        )

        # Apply confidence tiers
        final_result = apply_confidence_tiers(
            verified_result,
            high=settings.CRYSTALLIZER_CONFIDENCE_HIGH,
            low=settings.CRYSTALLIZER_CONFIDENCE_LOW,
        )

        # Merge chunk result into extraction_run.raw_extraction as a proper
        # ExtractionResult (entities/relations/claims lists). The FOR UPDATE
        # lock on the run row serializes concurrent chunk tasks.
        existing_raw = run.raw_extraction or {"entities": [], "relations": [], "claims": []}
        chunk_data = final_result.model_dump()
        existing_raw.setdefault("entities", []).extend(chunk_data.get("entities", []))
        existing_raw.setdefault("relations", []).extend(chunk_data.get("relations", []))
        existing_raw.setdefault("claims", []).extend(chunk_data.get("claims", []))
        run.raw_extraction = existing_raw

        # Update chunk to 'extracted'
        await chunk_repo.update_processing_stage(chunk.id, "extracted")

        # Write pipeline trace
        total_tokens = (
            usage_extract.tokens_in + usage_extract.tokens_out + usage_verify.tokens_in + usage_verify.tokens_out
        )
        total_cost = usage_extract.cost_usd + usage_verify.cost_usd
        await trace_repo.create(
            workspace_id=uuid.UUID(workspace_id),
            event_id=chunk.event_id,
            stage="crystallizer",
            decision="extracted",
            reason=f"chunk_id={chunk_id}, verified={True}, changed={verification_changed}",
            details={
                "entities": len(final_result.entities),
                "relations": len(final_result.relations),
                "claims": len(final_result.claims),
                "verification_changed": verification_changed,
            },
            tokens_used=total_tokens,
            cost_usd=total_cost,
            extraction_run_id=run.id,
        )

        # Update extraction_run.crystallizer_cost_usd
        run.crystallizer_cost_usd = float(run.crystallizer_cost_usd or 0) + total_cost

        await session.flush()
        event_id_for_check = chunk.event_id

    # Check AFTER commit — read committed state from a separate transaction
    all_extracted = False
    async with factory() as session2, session2.begin():
        await _set_workspace_context(session2, workspace_id)
        chunk_repo2 = ChunkRepository(session2, uuid.UUID(workspace_id))
        all_chunks = await chunk_repo2.list_by_event(event_id_for_check)
        crystal_chunks = [c for c in all_chunks if c.is_crystal]
        all_extracted = bool(crystal_chunks) and all(c.processing_stage == "extracted" for c in crystal_chunks)

    if all_extracted:
        await job_write.kiq(extraction_run_id, workspace_id)

    if redis_client:
        await redis_client.aclose()

    return {
        "chunk_id": chunk_id,
        "extraction_run_id": extraction_run_id,
        "entities": len(final_result.entities),
        "relations": len(final_result.relations),
        "claims": len(final_result.claims),
        "verification_changed": verification_changed,
        "status": "extracted",
    }


@broker.task(timeout=120, retry_on_error=True, max_retries=2)
async def job_enrich(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 3: Enrich — generate embeddings for extracted entities and claims."""
    from alayaos_core.extraction.pipeline import run_enrich
    from alayaos_core.services.embedding import FakeEmbeddingService, FastEmbedService

    settings = Settings()

    # Use FastEmbed in production, fake for dev/test
    if settings.FEATURE_FLAG_VECTOR_SEARCH:
        embedding_service = FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)
    else:
        embedding_service = FakeEmbeddingService(settings.EMBEDDING_DIMENSIONS)

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        await run_enrich(uuid.UUID(extraction_run_id), session, embedding_service=embedding_service)

    return {"extraction_run_id": extraction_run_id, "status": "enriched"}


@broker.task(timeout=300, retry_on_error=True, max_retries=2)
async def job_integrate(workspace_id: str, integrator_run_id: str | None = None) -> dict:
    """Integrator: process dirty_set union 48h window for a workspace."""
    settings = Settings()

    # Use real LLM adapter if key is available, else fake
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.INTEGRATOR_MODEL)
    else:
        from alayaos_core.llm.fake import FakeLLMAdapter

        llm = FakeLLMAdapter()

    redis_client = None
    with contextlib.suppress(Exception):
        redis_client = aioredis.from_url(settings.REDIS_URL)

    factory = _session_factory()
    ws_uuid = uuid.UUID(workspace_id)
    run_uuid: uuid.UUID | None = None
    try:
        if integrator_run_id is not None:
            run_uuid = uuid.UUID(integrator_run_id)
        else:
            run_uuid = await _create_integrator_run(
                factory,
                workspace_id,
                trigger="job_integrate",
                scope_description="dirty_set + 48h window",
                llm_model=settings.INTEGRATOR_MODEL,
            )

        async with factory() as session, session.begin():
            await _set_workspace_context(session, workspace_id)

            entity_repo = EntityRepository(session, ws_uuid)
            claim_repo = ClaimRepository(session, ws_uuid)
            relation_repo = RelationRepository(session, ws_uuid)
            run_repo = IntegratorRunRepository(session, ws_uuid)
            entity_cache = EntityCacheService(redis=redis_client)

            integrator_run = await run_repo.get_by_id(run_uuid)
            if integrator_run is None:
                raise ValueError("integrator run not found for workspace")

            engine = IntegratorEngine(
                llm=llm,
                entity_repo=entity_repo,
                claim_repo=claim_repo,
                relation_repo=relation_repo,
                entity_cache=entity_cache,
                redis=redis_client,
                settings=settings,
            )

            result = await engine.run(ws_uuid, session)

            # Update IntegratorRun with counters
            await run_repo.update_status(
                integrator_run.id,
                result.status,
                error_message=result.reason if result.status == "failed" else None,
            )
            await run_repo.update_counters(
                integrator_run.id,
                entities_scanned=result.entities_scanned,
                entities_deduplicated=result.entities_deduplicated,
                entities_enriched=result.entities_enriched,
                relations_created=result.relations_created,
                claims_updated=result.claims_updated,
                noise_removed=result.noise_removed,
                tokens_used=result.tokens_used,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
            )
    except Exception as exc:
        if run_uuid is not None:
            with contextlib.suppress(Exception):
                await _mark_integrator_run_failed(factory, workspace_id, run_uuid, str(exc))
        raise
    finally:
        if redis_client:
            await redis_client.aclose()

    return {
        "workspace_id": workspace_id,
        "status": result.status,
        "entities_scanned": result.entities_scanned,
        "entities_deduplicated": result.entities_deduplicated,
    }


@broker.task(timeout=30, schedule=[{"cron": "* * * * *"}])
async def job_check_integrator() -> dict:
    """Periodic task: check all dirty-sets and trigger job_integrate if thresholds met.

    Runs every minute via TaskIQ scheduler (LabelScheduleSource).
    """
    from datetime import UTC, datetime

    settings = Settings()
    redis_client = aioredis.from_url(settings.REDIS_URL)
    factory = _session_factory()
    try:
        reaped = await _reap_stuck_integrator_runs(
            factory,
            stuck_after_seconds=getattr(settings, "INTEGRATOR_STUCK_RUN_SECONDS", 900),
        )
        cursor = 0
        triggered: list[str] = []
        while True:
            cursor, keys = await redis_client.scan(cursor, match="dirty_set:*", count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                # Skip companion keys and processing keys
                if ":created_at" in key_str or ":processing" in key_str:
                    continue
                workspace_id = key_str.split(":")[1]
                size = await redis_client.scard(key_str)
                # Check age via companion key
                created_at_key = f"dirty_set:{workspace_id}:created_at"
                created_at_str = await redis_client.get(created_at_key)
                age_exceeded = False
                if created_at_str:
                    created = datetime.fromisoformat(
                        created_at_str.decode() if isinstance(created_at_str, bytes) else created_at_str
                    )
                    age = (datetime.now(UTC) - created).total_seconds()
                    age_exceeded = age >= settings.INTEGRATOR_MAX_WAIT_SECONDS
                if size >= settings.INTEGRATOR_DIRTY_SET_THRESHOLD or age_exceeded:
                    await job_integrate.kiq(workspace_id)
                    triggered.append(workspace_id)
            if cursor == 0:
                break
        return {"triggered": triggered, "reaped": reaped, "status": "checked"}
    finally:
        await redis_client.aclose()
