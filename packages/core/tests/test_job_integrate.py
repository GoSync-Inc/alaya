"""Tests for job_integrate TaskIQ task."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_job_integrate_returns_dict():
    """job_integrate returns a dict with workspace_id and status."""
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult

    ws_id = uuid.uuid4()

    mock_run = MagicMock()
    mock_run.id = uuid.uuid4()

    mock_engine_result = IntegratorRunResult(
        status="completed",
        entities_scanned=3,
        entities_deduplicated=1,
    )

    mock_engine_instance = AsyncMock()
    mock_engine_instance.run = AsyncMock(return_value=mock_engine_result)

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks.IntegratorEngine", return_value=mock_engine_instance),
        patch("alayaos_core.worker.tasks.IntegratorRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks.EntityCacheService"),
        patch("alayaos_core.worker.tasks.EntityRepository"),
        patch("alayaos_core.worker.tasks.ClaimRepository"),
        patch("alayaos_core.worker.tasks.RelationRepository"),
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_integrate

        result = await job_integrate(str(ws_id))

    assert isinstance(result, dict)
    assert "workspace_id" in result
    assert "status" in result


@pytest.mark.asyncio
async def test_job_integrate_calls_engine_run():
    """job_integrate creates IntegratorEngine and calls run()."""
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult

    ws_id = uuid.uuid4()

    mock_run = MagicMock()
    mock_run.id = uuid.uuid4()

    mock_engine_result = IntegratorRunResult(status="completed")
    mock_engine_instance = AsyncMock()
    mock_engine_instance.run = AsyncMock(return_value=mock_engine_result)

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    mock_engine_cls = MagicMock(return_value=mock_engine_instance)

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks.IntegratorEngine", mock_engine_cls),
        patch("alayaos_core.worker.tasks.IntegratorRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=AsyncMock()),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks.EntityCacheService"),
        patch("alayaos_core.worker.tasks.EntityRepository"),
        patch("alayaos_core.worker.tasks.ClaimRepository"),
        patch("alayaos_core.worker.tasks.RelationRepository"),
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_integrate

        await job_integrate(str(ws_id))

    mock_engine_instance.run.assert_called_once()
