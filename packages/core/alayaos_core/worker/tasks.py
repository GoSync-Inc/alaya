"""TaskIQ task definitions for the three-job extraction pipeline."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.worker.broker import broker


async def _set_workspace_context(session: AsyncSession, workspace_id: str) -> None:
    """Set RLS workspace context for the current transaction."""
    await session.execute(text("SET LOCAL app.workspace_id = :wid"), {"wid": workspace_id})


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


@broker.task(timeout=60, retry_on_error=True, max_retries=2)
async def job_enrich(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 3: Enrich — embedding stub (deferred to Run 3)."""
    from alayaos_core.extraction.pipeline import run_enrich

    factory = _session_factory()
    async with factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        await run_enrich(uuid.UUID(extraction_run_id), session)

    return {"extraction_run_id": extraction_run_id, "status": "enriched"}
