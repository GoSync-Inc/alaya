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
    """Access level gate. Sets run.status='skipped' if denied."""
    if event.access_level == "restricted":
        log.info("skipping_restricted", event_id=str(event.id))
        await run_repo.update_status(run.id, "skipped", error_message="access_level=restricted")
        return False
    if event.access_level == "private":
        ws_repo = WorkspaceRepository(session)
        workspace = await ws_repo.get_by_id(event.workspace_id)
        if workspace and not workspace.settings.get("extract_private", False):
            log.info("skipping_private_no_optin", event_id=str(event.id))
            await run_repo.update_status(run.id, "skipped", error_message="private without opt-in")
            return False
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

    event = await event_repo.get_by_id(event_id)
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

    event = await event_repo.get_by_id(run.event_id) if run.event_id else None
    if not event:
        await run_repo.update_status(run.id, "failed", error_message="event not found")
        return None

    raw = run.raw_extraction
    if not raw:
        await run_repo.update_status(run.id, "failed", error_message="no raw_extraction")
        return None

    extraction_result = ExtractionResult.model_validate(raw)

    # Acquire workspace lock
    token = None
    if redis:
        token = await acquire_workspace_lock(redis, str(event.workspace_id))
        if not token:
            raise RuntimeError(f"Could not acquire workspace lock for {event.workspace_id}")

    try:
        await run_repo.update_status(run.id, "writing")
        counters = await atomic_write(extraction_result, event, run, session, llm)
        await run_repo.update_status(run.id, "completed")
        return counters
    except Exception as e:
        await run_repo.update_status(run.id, "failed", error_message=str(e))
        raise
    finally:
        if redis and token:
            await release_workspace_lock(redis, str(event.workspace_id), token)


async def run_enrich(run_id: uuid.UUID, session: AsyncSession) -> None:
    """Job 3: Enrich stub — mark entities as needing embedding."""
    run_repo = ExtractionRunRepository(session)
    run = await run_repo.get_by_id(run_id)
    if not run or run.status != "completed":
        return
    await run_repo.update_status(run.id, "enriching")
    # Actual embedding deferred to Run 3
    log.info("enrich_stub_completed", run_id=str(run_id))
