"""Integration tests for workspace-level write serialization."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from alayaos_core.extraction.pipeline import run_write
from alayaos_core.models.event import L0Event
from alayaos_core.models.extraction_run import ExtractionRun
from alayaos_core.models.workspace import Workspace


def _make_counters() -> dict[str, int]:
    return {
        "entities_created": 0,
        "entities_merged": 0,
        "relations_created": 0,
        "claims_created": 0,
        "claims_superseded": 0,
    }


@pytest.mark.asyncio
async def test_run_write_serializes_concurrent_writes_with_workspace_lock(engine) -> None:
    """A second write waits behind the workspace row lock instead of racing atomic_write."""
    workspace_id = uuid.uuid4()
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as seed_session, seed_session.begin():
        await seed_session.execute(text(f"SET LOCAL app.workspace_id = '{workspace_id}'"))
        seed_session.add(
            Workspace(
                id=workspace_id,
                name="Workspace Lock Test",
                slug=f"ws-lock-{workspace_id.hex[:8]}",
            )
        )
        seed_session.add(
            L0Event(
                id=event_id,
                workspace_id=workspace_id,
                source_type="manual",
                source_id="lock-test",
                content={"text": "Alice owns Project Phoenix."},
                raw_text="Alice owns Project Phoenix.",
                access_level="public",
                occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        seed_session.add(
            ExtractionRun(
                id=run_id,
                workspace_id=workspace_id,
                event_id=event_id,
                status="pending",
                raw_extraction={"entities": [], "relations": [], "claims": []},
            )
        )

    first_atomic_started = asyncio.Event()
    second_atomic_started = asyncio.Event()
    release_first_atomic = asyncio.Event()
    call_count = 0

    async def fake_atomic_write(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            first_atomic_started.set()
            await release_first_atomic.wait()
        else:
            second_atomic_started.set()
        return _make_counters()

    async def _run_once() -> dict | None:
        async with session_factory() as session, session.begin():
            await session.execute(text(f"SET LOCAL app.workspace_id = '{workspace_id}'"))
            return await run_write(run_id=run_id, session=session, llm=AsyncMock(), redis=None)

    with patch("alayaos_core.extraction.pipeline.atomic_write", new=fake_atomic_write):
        task1 = asyncio.create_task(_run_once())
        await asyncio.wait_for(first_atomic_started.wait(), timeout=5)

        task2 = asyncio.create_task(_run_once())
        await asyncio.sleep(0.2)
        assert second_atomic_started.is_set() is False

        release_first_atomic.set()
        result1 = await asyncio.wait_for(task1, timeout=5)
        assert result1 == _make_counters()

        await asyncio.wait_for(second_atomic_started.wait(), timeout=5)
        result2 = await asyncio.wait_for(task2, timeout=5)
        assert result2 == _make_counters()
