"""Backfill extraction for existing restricted events."""

from __future__ import annotations

import argparse
import uuid
from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.repositories.extraction_run import ExtractionRunRepository


class _DryRunRollback(Exception):  # noqa: N818 - spec names this sentinel explicitly.
    """Sentinel to roll back the dry-run SELECT transaction."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True, type=uuid.UUID)
    parser.add_argument("--limit", type=int, default=10_000)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def _build_session_factory() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    settings = Settings()
    engine = create_async_engine(settings.DATABASE_URL.get_secret_value(), echo=settings.DB_ECHO)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def _set_workspace_context(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": str(workspace_id)},
    )


async def enqueue_extraction(
    event_id: uuid.UUID,
    workspace_id: uuid.UUID,
    session_factory: Callable[[], AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await _set_workspace_context(session, workspace_id)
        run_repo = ExtractionRunRepository(session, workspace_id)
        run = await run_repo.create(workspace_id=workspace_id, event_id=event_id, status="pending")

    tasks_module = import_module("alayaos_core.worker.tasks")
    job_extract = cast("Any", tasks_module).job_extract
    await job_extract.kiq(str(event_id), str(run.id), str(workspace_id))


async def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], AsyncSession] | None = None,
    enqueue: Callable[[uuid.UUID], Awaitable[None]] | None = None,
) -> int:
    args = parse_args(argv)
    event_ids: list[uuid.UUID] = []
    engine: AsyncEngine | None = None

    factory = session_factory
    if factory is None:
        factory, engine = _build_session_factory()
    enqueue_event: Callable[[uuid.UUID], Awaitable[None]]
    if enqueue is None:

        async def _enqueue_event(event_id: uuid.UUID) -> None:
            await enqueue_extraction(event_id, args.workspace_id, factory)

        enqueue_event = _enqueue_event
    else:
        enqueue_event = enqueue

    try:
        async with factory() as session:
            try:
                async with session.begin():
                    await _set_workspace_context(session, args.workspace_id)
                    result = await session.execute(
                        text(
                            """
                            SELECT e.id FROM l0_events e
                            WHERE e.workspace_id = :ws
                              AND e.access_level = 'restricted'
                              AND e.is_extracted = false
                            ORDER BY e.created_at
                            LIMIT :limit
                            FOR UPDATE SKIP LOCKED
                            """
                        ),
                        {"ws": args.workspace_id, "limit": args.limit},
                    )
                    event_ids = [row["id"] for row in result.mappings()]

                    if args.dry_run:
                        print(f"[dry-run] Would enqueue {len(event_ids)} events. Use --apply to execute.")
                        raise _DryRunRollback()
            except _DryRunRollback:
                return 0

        for event_id in event_ids:
            await enqueue_event(event_id)
        print(f"[apply] Enqueued {len(event_ids)} events for extraction.")
        return len(event_ids)
    finally:
        if engine is not None:
            await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
