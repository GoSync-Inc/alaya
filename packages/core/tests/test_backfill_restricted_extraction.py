"""Tests for restricted-event extraction backfill script."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest


class _FakeResult:
    def __init__(self, event_ids: list[uuid.UUID]) -> None:
        self._event_ids = event_ids

    def mappings(self) -> list[dict]:
        return [{"id": event_id} for event_id in self._event_ids]


class _FakeTransaction:
    def __init__(self, order: list[str] | None = None) -> None:
        self.committed = False
        self.rolled_back = False
        self._order = order

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        if self._order is not None:
            self._order.append("rollback" if self.rolled_back else "commit")
        return False


class _FakeSession:
    def __init__(self, event_ids: list[uuid.UUID], order: list[str] | None = None) -> None:
        self.event_ids = event_ids
        self.transaction = _FakeTransaction(order)
        self.execute_params: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self) -> _FakeTransaction:
        return self.transaction

    async def execute(self, _stmt, params: dict) -> _FakeResult:
        self.execute_params = params
        return _FakeResult(self.event_ids)


@pytest.mark.asyncio
async def test_dry_run_rolls_back_selected_events_and_does_not_enqueue(capsys) -> None:
    from alayaos_core.scripts.backfill_restricted_extraction import main

    workspace_id = uuid.uuid4()
    event_id = uuid.uuid4()
    session = _FakeSession([event_id])
    enqueue = AsyncMock()

    await main(
        ["--workspace-id", str(workspace_id), "--dry-run", "--limit", "5"],
        session_factory=lambda: session,
        enqueue=enqueue,
    )

    assert session.execute_params == {"ws": workspace_id, "limit": 5}
    assert session.transaction.rolled_back is True
    assert session.transaction.committed is False
    enqueue.assert_not_awaited()
    assert "[dry-run] Would enqueue 1 events." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_apply_commits_select_transaction_before_enqueue(capsys) -> None:
    from alayaos_core.scripts.backfill_restricted_extraction import main

    workspace_id = uuid.uuid4()
    first_event_id = uuid.uuid4()
    second_event_id = uuid.uuid4()
    order: list[str] = []
    session = _FakeSession([first_event_id, second_event_id], order)
    enqueued: list[uuid.UUID] = []

    async def enqueue(event_id: uuid.UUID) -> None:
        assert session.transaction.committed is True
        order.append(f"enqueue:{event_id}")
        enqueued.append(event_id)

    count = await main(
        ["--workspace-id", str(workspace_id), "--apply"],
        session_factory=lambda: session,
        enqueue=enqueue,
    )

    assert count == 2
    assert session.transaction.committed is True
    assert order == ["commit", f"enqueue:{first_event_id}", f"enqueue:{second_event_id}"]
    assert enqueued == [first_event_id, second_event_id]
    assert "[apply] Enqueued 2 events for extraction." in capsys.readouterr().out
