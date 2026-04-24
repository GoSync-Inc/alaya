"""Extraction pipeline orchestration — three jobs: extract, write, enrich."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.extraction.writer import acquire_workspace_lock, atomic_write, release_workspace_lock
from alayaos_core.repositories.event import EventRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.repositories.workspace import WorkspaceRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.extraction.extractor import Extractor
    from alayaos_core.extraction.preprocessor import Preprocessor
    from alayaos_core.llm.interface import LLMServiceInterface

log = structlog.get_logger()


async def should_extract(event, run, run_repo, session) -> bool:
    """Access-level observability; retrieval gates visibility after extraction."""
    # Run 6.2 merge-order note: access_level="channel" is tier 1 at retrieval,
    # but extracts identically to public here.
    # Restricted also extracts and retrieval ACL gates visibility; private
    # remains workspace opt-in gated.
    if event.access_level == "restricted":
        log.info(
            "extraction.sensitive_event_extracting",
            event_id=str(event.id),
            access_level=event.access_level,
        )
    if event.access_level == "private":
        ws_repo = WorkspaceRepository(session)
        workspace = await ws_repo.get_by_id(event.workspace_id)
        if not workspace or not workspace.settings.get("extract_private", False):
            log.info("skipping_private_no_optin", event_id=str(event.id))
            await run_repo.update_status(run.id, "skipped", error_message="private without opt-in")
            return False
        log.info(
            "extraction.sensitive_event_extracting",
            event_id=str(event.id),
            access_level=event.access_level,
        )
    return True


async def run_extraction(
    event_id: uuid.UUID,
    run_id: uuid.UUID,
    session: AsyncSession,
    llm: LLMServiceInterface,
    preprocessor: Preprocessor,
    extractor: Extractor,
    entity_types: list[dict],
    predicates: list[dict],
) -> ExtractionResult | None:
    """Job 1: Extract — preprocess, call LLM, store raw extraction."""
    event_repo = EventRepository(session)
    run_repo = ExtractionRunRepository(session)

    event = await event_repo.get_by_id_unfiltered(event_id)
    run = await run_repo.get_by_id(run_id)
    if not event or not run:
        return None

    # Idempotency check
    if run.status == "completed":
        return None

    # Access gate
    if not await should_extract(event, run, run_repo, session):
        return None

    await run_repo.update_status(run.id, "extracting")

    # Preprocess
    text = event.raw_text or event.content.get("text", "")
    chunks = preprocessor.chunk(text, event.source_type, event.source_id)

    # Build system prompt
    system_prompt = extractor.build_system_prompt(entity_types, predicates)

    # Extract each chunk
    merged = ExtractionResult()
    total_tokens_in = 0
    total_tokens_out = 0
    total_tokens_cached = 0
    total_cost = 0.0

    extracted_entity_names: list[str] = []
    for chunk in chunks:
        preprocessor.propagate_entities(chunks, extracted_entity_names)
        token_count = preprocessor.count_tokens(chunk.text)
        result, usage = await extractor.extract_with_gleaning(chunk, system_prompt, token_count)

        merged.entities.extend(result.entities)
        merged.relations.extend(result.relations)
        merged.claims.extend(result.claims)
        extracted_entity_names.extend(e.name for e in result.entities)

        total_tokens_in += usage.tokens_in
        total_tokens_out += usage.tokens_out
        total_tokens_cached += usage.tokens_cached
        total_cost += usage.cost_usd

    # Store raw extraction
    await run_repo.store_raw_extraction(run.id, merged.model_dump())

    # Update LLM stats
    run.tokens_in = total_tokens_in
    run.tokens_out = total_tokens_out
    run.tokens_cached = total_tokens_cached
    run.cost_usd = total_cost
    from alayaos_core.config import Settings

    settings = Settings()
    run.llm_provider = settings.EXTRACTION_LLM_PROVIDER
    run.llm_model = settings.ANTHROPIC_MODEL
    await session.flush()

    return merged


async def run_write(
    run_id: uuid.UUID,
    session: AsyncSession,
    llm: LLMServiceInterface,
    redis=None,
) -> dict | None:
    """Job 2: Write — load raw extraction, resolve, write atomically."""
    run_repo = ExtractionRunRepository(session)
    event_repo = EventRepository(session)

    run = await run_repo.get_by_id(run_id)
    if not run or run.status == "completed":
        return None

    event = await event_repo.get_by_id_unfiltered(run.event_id) if run.event_id else None
    if not event:
        await run_repo.update_status(run.id, "failed", error_message="event not found")
        return None

    workspace_repo = WorkspaceRepository(session)
    workspace = await workspace_repo.get_by_id_for_update(event.workspace_id)
    if not workspace:
        await run_repo.update_status(run_id, "failed", error_message="workspace not found")
        return None

    run = await run_repo.get_by_id(run.id)
    if not run:
        await run_repo.update_status(run_id, "failed", error_message="run not found")
        return None
    if run.status == "completed":
        return None

    raw = run.raw_extraction
    if not raw:
        await run_repo.update_status(run.id, "failed", error_message="no raw_extraction")
        return None

    extraction_result = ExtractionResult.model_validate(raw)

    # Optional Redis fast-path lock; correctness comes from the DB row lock.
    token = None
    if redis:
        try:
            token = await acquire_workspace_lock(redis, str(event.workspace_id))
        except Exception as exc:
            log.warning(
                "workspace_redis_lock_degraded",
                workspace_id=str(event.workspace_id),
                error=str(exc),
            )
        if token is None:
            log.info("workspace_redis_lock_unavailable", workspace_id=str(event.workspace_id))

    try:
        await run_repo.update_status(run.id, "writing")
        counters = await atomic_write(extraction_result, event, run, session, llm, redis=redis)

        # Wire tree dirty flags — mark entity-linked nodes as needing rebuild
        try:
            from alayaos_core.repositories.tree import TreeNodeRepository

            tree_repo = TreeNodeRepository(session, event.workspace_id)
            dirty_count = await tree_repo.mark_workspace_dirty()
            if dirty_count:
                log.info("tree_dirty_flagged", run_id=str(run_id), count=dirty_count)
        except Exception:
            log.warning("tree_dirty_flag_failed", run_id=str(run_id))

        await run_repo.update_status(run.id, "completed")
        return counters
    except Exception as e:
        await run_repo.update_status(run.id, "failed", error_message=str(e))
        raise
    finally:
        if redis and token:
            await release_workspace_lock(redis, str(event.workspace_id), token)


async def run_enrich(
    run_id: uuid.UUID,
    session: AsyncSession,
    embedding_service=None,
) -> None:
    """Job 3: Enrich — generate embeddings for entities and claims from this extraction run."""
    from sqlalchemy import select

    from alayaos_core.models.claim import L2Claim
    from alayaos_core.models.entity import L1Entity
    from alayaos_core.repositories.vector import VectorChunkRepository

    run_repo = ExtractionRunRepository(session)
    run = await run_repo.get_by_id(run_id)
    if not run or run.status != "completed":
        return

    if embedding_service is None:
        log.info("enrich_no_embedding_service", run_id=str(run_id))
        return

    await run_repo.update_status(run.id, "enriching")

    ws_id = run.workspace_id

    # Load entities created by this run
    entity_stmt = select(L1Entity).where(L1Entity.workspace_id == ws_id, L1Entity.extraction_run_id == run_id)
    entities = list((await session.execute(entity_stmt)).scalars().all())

    claim_stmt = select(L2Claim).where(L2Claim.workspace_id == ws_id, L2Claim.extraction_run_id == run_id)
    claims = list((await session.execute(claim_stmt)).scalars().all())

    # Build text representations
    texts: list[str] = []
    source_info: list[dict] = []

    for entity in entities:
        text = entity.name
        texts.append(text)
        source_info.append({"source_type": "entity", "source_id": entity.id, "content": text})

    for claim in claims:
        text = f"{claim.predicate}: {claim.value}"
        texts.append(text)
        source_info.append({"source_type": "claim", "source_id": claim.id, "content": text})

    if not texts:
        log.info("enrich_nothing_to_embed", run_id=str(run_id))
        await run_repo.update_status(run.id, "completed")
        return

    # Batch embed
    embeddings = await embedding_service.embed_texts(texts)

    # Create VectorChunk rows
    vector_repo = VectorChunkRepository(session, ws_id)
    chunk_rows: list[dict] = []
    for info, embedding in zip(source_info, embeddings, strict=True):
        access_level = await vector_repo.get_access_level_for_source(info["source_type"], info["source_id"])
        chunk_rows.append(
            {
                "workspace_id": ws_id,
                "source_type": info["source_type"],
                "source_id": info["source_id"],
                "chunk_index": 0,
                "content": info["content"],
                "embedding": embedding,
                "access_level": access_level,
            }
        )

    await vector_repo.create_batch(chunk_rows)
    log.info("enrich_completed", run_id=str(run_id), chunks_created=len(texts))
    await run_repo.update_status(run.id, "completed")
