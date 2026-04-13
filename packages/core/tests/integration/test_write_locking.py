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
    first_run_id = uuid.uuid4()
    second_run_id = uuid.uuid4()

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
                id=first_run_id,
                workspace_id=workspace_id,
                event_id=event_id,
                status="pending",
                raw_extraction={"entities": [], "relations": [], "claims": []},
            )
        )
        seed_session.add(
            ExtractionRun(
                id=second_run_id,
                workspace_id=workspace_id,
                event_id=event_id,
                status="pending",
                raw_extraction={"entities": [], "relations": [], "claims": []},
            )
        )

    first_atomic_started = asyncio.Event()
    second_atomic_started = asyncio.Event()
    release_first_atomic = asyncio.Event()
    first_atomic_calls = 0
    second_atomic_calls = 0

    async def fake_atomic_write(_result, _event, run, *_args, **_kwargs):
        nonlocal first_atomic_calls, second_atomic_calls
        if run.id == first_run_id:
            first_atomic_calls += 1
            first_atomic_started.set()
            await release_first_atomic.wait()
            return _make_counters()
        if run.id == second_run_id:
            second_atomic_calls += 1
            second_atomic_started.set()
            return _make_counters()
        raise AssertionError(f"unexpected run id: {run.id}")

    async def _run_once(run_id: uuid.UUID) -> dict | None:
        async with session_factory() as session, session.begin():
            await session.execute(text(f"SET LOCAL app.workspace_id = '{workspace_id}'"))
            return await run_write(run_id=run_id, session=session, llm=AsyncMock(), redis=None)

    with patch("alayaos_core.extraction.pipeline.atomic_write", new=fake_atomic_write):
        task1 = asyncio.create_task(_run_once(first_run_id))
        await asyncio.wait_for(first_atomic_started.wait(), timeout=5)

        task2 = asyncio.create_task(_run_once(second_run_id))
        await asyncio.sleep(0.2)
        assert second_atomic_started.is_set() is False

        release_first_atomic.set()
        result1 = await asyncio.wait_for(task1, timeout=5)
        assert result1 == _make_counters()

        await asyncio.wait_for(second_atomic_started.wait(), timeout=5)
        result2 = await asyncio.wait_for(task2, timeout=5)
        assert result2 == _make_counters()
        assert first_atomic_calls == 1
        assert second_atomic_calls == 1
