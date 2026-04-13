"""Tests for worker-scoped database resources."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from taskiq.events import TaskiqEvents


@pytest.fixture(autouse=True)
def reset_worker_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    from alayaos_core.worker import tasks as worker_tasks

    monkeypatch.setattr(worker_tasks, "_engine", None, raising=False)
    monkeypatch.setattr(worker_tasks, "_session_factory_cached", None, raising=False)


def test_get_session_factory_reuses_engine_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from alayaos_core.worker import tasks as worker_tasks

    factory_marker = MagicMock(name="session_factory")
    engine = AsyncMock()

    monkeypatch.setattr(worker_tasks, "_engine", None, raising=False)
    monkeypatch.setattr(worker_tasks, "_session_factory_cached", None, raising=False)

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=MagicMock(DATABASE_URL="postgresql+asyncpg://test")),
        patch("alayaos_core.worker.tasks.create_async_engine", return_value=engine) as mock_create_engine,
        patch("alayaos_core.worker.tasks.async_sessionmaker", return_value=factory_marker) as mock_sessionmaker,
    ):
        factory_a = worker_tasks._get_session_factory()
        factory_b = worker_tasks._get_session_factory()

    assert factory_a is factory_marker
    assert factory_b is factory_marker
    mock_create_engine.assert_called_once()
    mock_sessionmaker.assert_called_once_with(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_close_worker_resources_disposes_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    from alayaos_core.worker import tasks as worker_tasks

    first_factory = MagicMock(name="first_factory")
    second_factory = MagicMock(name="second_factory")
    first_engine = AsyncMock()
    second_engine = AsyncMock()

    monkeypatch.setattr(worker_tasks, "_engine", None, raising=False)
    monkeypatch.setattr(worker_tasks, "_session_factory_cached", None, raising=False)

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=MagicMock(DATABASE_URL="postgresql+asyncpg://test")),
        patch(
            "alayaos_core.worker.tasks.create_async_engine",
            side_effect=[first_engine, second_engine],
        ) as mock_create_engine,
        patch(
            "alayaos_core.worker.tasks.async_sessionmaker",
            side_effect=[first_factory, second_factory],
        ) as mock_sessionmaker,
    ):
        factory_a = worker_tasks._get_session_factory()

        await worker_tasks.close_worker_resources()

        factory_b = worker_tasks._get_session_factory()

    assert factory_a is first_factory
    assert factory_b is second_factory
    first_engine.dispose.assert_awaited_once()
    assert worker_tasks._engine is second_engine
    assert worker_tasks._session_factory_cached is second_factory
    assert mock_create_engine.call_count == 2
    assert mock_sessionmaker.call_count == 2


def test_worker_shutdown_hook_registered() -> None:
    from alayaos_core.worker import tasks as worker_tasks
    from alayaos_core.worker.broker import broker

    assert worker_tasks._close_worker_resources_on_shutdown in broker.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]
