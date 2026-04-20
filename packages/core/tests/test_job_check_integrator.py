"""Tests for job_check_integrator periodic task."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr


def _make_redis_with_keys(keys: list[str], sizes: dict[str, int], created_ats: dict[str, str]):
    """Create a mock Redis with scan/scard/get behaviour."""
    redis_mock = AsyncMock()

    # scan: return all keys in one shot
    async def mock_scan(cursor, match=None, count=None):
        if cursor == 0:
            matched = [k.encode() for k in keys if match is None or _match_pattern(k, match)]
            return (0, matched)
        return (0, [])

    def _match_pattern(key, pattern):
        import fnmatch

        return fnmatch.fnmatch(key, pattern)

    redis_mock.scan = mock_scan

    async def mock_scard(key):
        key_str = key.decode() if isinstance(key, bytes) else key
        return sizes.get(key_str, 0)

    redis_mock.scard = mock_scard

    async def mock_get(key):
        key_str = key.decode() if isinstance(key, bytes) else key
        val = created_ats.get(key_str)
        return val.encode() if val else None

    redis_mock.get = mock_get
    redis_mock.aclose = AsyncMock()
    return redis_mock


@pytest.mark.asyncio
async def test_job_check_integrator_triggers_when_threshold_met():
    """job_check_integrator triggers job_integrate when dirty-set size >= threshold."""
    ws_id = str(uuid.uuid4())
    dirty_key = f"dirty_set:{ws_id}"

    redis_mock = _make_redis_with_keys(
        keys=[dirty_key],
        sizes={dirty_key: 15},  # > INTEGRATOR_DIRTY_SET_THRESHOLD=10
        created_ats={},
    )

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1800

    mock_kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=0)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker.tasks import job_check_integrator

        with patch.object(job_check_integrator, "kiq", mock_kiq):
            # We need to patch job_integrate.kiq
            from alayaos_core.worker import tasks as tasks_mod

            with patch.object(tasks_mod.job_integrate, "kiq", mock_kiq):
                result = await job_check_integrator()

    assert "triggered" in result
    assert ws_id in result["triggered"]
    mock_kiq.assert_awaited_once_with(ws_id)


@pytest.mark.asyncio
async def test_job_check_integrator_triggers_when_age_exceeded():
    """job_check_integrator triggers when dirty-set age >= MAX_WAIT_SECONDS."""
    ws_id = str(uuid.uuid4())
    dirty_key = f"dirty_set:{ws_id}"
    created_at_key = f"dirty_set:{ws_id}:created_at"

    # Created 2 hours ago, max wait is 1 second (test: exceeded)
    old_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat()
    redis_mock = _make_redis_with_keys(
        keys=[dirty_key, created_at_key],
        sizes={dirty_key: 2},  # below threshold
        created_ats={created_at_key: old_time},
    )

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1  # very short

    mock_kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=0)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker import tasks as tasks_mod

        with patch.object(tasks_mod.job_integrate, "kiq", mock_kiq):
            result = await tasks_mod.job_check_integrator()

    assert "triggered" in result
    assert ws_id in result["triggered"]


@pytest.mark.asyncio
async def test_job_check_integrator_skips_companion_keys():
    """job_check_integrator skips :created_at and :processing companion keys."""
    ws_id = str(uuid.uuid4())
    dirty_key = f"dirty_set:{ws_id}"
    created_at_key = f"dirty_set:{ws_id}:created_at"
    processing_key = f"dirty_set:{ws_id}:processing"

    redis_mock = _make_redis_with_keys(
        keys=[dirty_key, created_at_key, processing_key],
        sizes={dirty_key: 15, created_at_key: 0, processing_key: 0},
        created_ats={},
    )

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1800

    mock_kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=0)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker import tasks as tasks_mod

        with patch.object(tasks_mod.job_integrate, "kiq", mock_kiq):
            result = await tasks_mod.job_check_integrator()

    # Only the real dirty-set key should have triggered
    assert result["triggered"].count(ws_id) == 1


@pytest.mark.asyncio
async def test_job_check_integrator_no_trigger_when_below_threshold():
    """job_check_integrator does NOT trigger when size below threshold and not old."""
    ws_id = str(uuid.uuid4())
    dirty_key = f"dirty_set:{ws_id}"
    created_at_key = f"dirty_set:{ws_id}:created_at"

    # Recent created_at, below threshold size
    recent_time = datetime.now(UTC).isoformat()
    redis_mock = _make_redis_with_keys(
        keys=[dirty_key, created_at_key],
        sizes={dirty_key: 3},  # below threshold of 10
        created_ats={created_at_key: recent_time},
    )

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1800  # 30 min

    mock_kiq = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=0)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker import tasks as tasks_mod

        with patch.object(tasks_mod.job_integrate, "kiq", mock_kiq):
            result = await tasks_mod.job_check_integrator()

    assert result["triggered"] == []


@pytest.mark.asyncio
async def test_job_check_integrator_returns_status_checked():
    """job_check_integrator always returns status='checked'."""
    redis_mock = _make_redis_with_keys(keys=[], sizes={}, created_ats={})

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1800

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=0)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker import tasks as tasks_mod

        result = await tasks_mod.job_check_integrator()

    assert result["status"] == "checked"


@pytest.mark.asyncio
async def test_reap_stuck_integrator_runs_marks_old_runs_across_workspaces() -> None:
    ws1 = MagicMock()
    ws1.id = uuid.uuid4()
    ws2 = MagicMock()
    ws2.id = uuid.uuid4()

    list_session = AsyncMock()
    list_session.__aenter__ = AsyncMock(return_value=list_session)
    list_session.__aexit__ = AsyncMock(return_value=False)

    ws1_session = AsyncMock()
    ws1_session.__aenter__ = AsyncMock(return_value=ws1_session)
    ws1_session.__aexit__ = AsyncMock(return_value=False)
    ws1_session.begin = MagicMock()
    ws1_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    ws1_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    ws2_session = AsyncMock()
    ws2_session.__aenter__ = AsyncMock(return_value=ws2_session)
    ws2_session.__aexit__ = AsyncMock(return_value=False)
    ws2_session.begin = MagicMock()
    ws2_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    ws2_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(side_effect=[list_session, ws1_session, ws2_session])
    workspace_repo = AsyncMock()
    workspace_repo.list = AsyncMock(
        side_effect=[
            ([ws1], "cursor-1", True),
            ([ws2], None, False),
        ]
    )
    run_repo_1 = AsyncMock()
    run_repo_1.mark_stale_running_failed = AsyncMock(return_value=1)
    run_repo_2 = AsyncMock()
    run_repo_2.mark_stale_running_failed = AsyncMock(return_value=2)
    mock_set_workspace_context = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks.WorkspaceRepository", return_value=workspace_repo),
        patch(
            "alayaos_core.worker.tasks.IntegratorRunRepository",
            side_effect=[run_repo_1, run_repo_2],
        ),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=mock_set_workspace_context),
    ):
        from alayaos_core.worker.tasks import _reap_stuck_integrator_runs

        reaped = await _reap_stuck_integrator_runs(factory, stuck_after_seconds=900)

    assert reaped == 3
    assert workspace_repo.list.await_count == 2
    run_repo_1.mark_stale_running_failed.assert_awaited_once()
    run_repo_2.mark_stale_running_failed.assert_awaited_once()
    mock_set_workspace_context.assert_any_await(ws1_session, str(ws1.id))
    mock_set_workspace_context.assert_any_await(ws2_session, str(ws2.id))


@pytest.mark.asyncio
async def test_job_check_integrator_reports_reaped_runs() -> None:
    redis_mock = _make_redis_with_keys(keys=[], sizes={}, created_ats={})

    mock_settings = MagicMock()
    mock_settings.REDIS_URL = SecretStr("redis://localhost")
    mock_settings.INTEGRATOR_DIRTY_SET_THRESHOLD = 10
    mock_settings.INTEGRATOR_MAX_WAIT_SECONDS = 1800
    mock_settings.INTEGRATOR_STUCK_RUN_SECONDS = 900

    with (
        patch("alayaos_core.worker.tasks.Settings", return_value=mock_settings),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks._session_factory", return_value=MagicMock()),
        patch("alayaos_core.worker.tasks._reap_stuck_integrator_runs", new=AsyncMock(return_value=2)),
    ):
        mock_aioredis.from_url.return_value = redis_mock

        from alayaos_core.worker import tasks as tasks_mod

        result = await tasks_mod.job_check_integrator()

    assert result["reaped"] == 2
