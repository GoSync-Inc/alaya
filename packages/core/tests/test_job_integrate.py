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


@pytest.mark.asyncio
async def test_job_integrate_reuses_existing_run_when_supplied() -> None:
    """job_integrate should reuse a caller-created IntegratorRun when one is supplied."""
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult

    ws_id = uuid.uuid4()
    existing_run = MagicMock()
    existing_run.id = uuid.uuid4()
    existing_run.workspace_id = ws_id

    mock_engine_result = IntegratorRunResult(status="completed")
    mock_engine_instance = AsyncMock()
    mock_engine_instance.run = AsyncMock(return_value=mock_engine_result)

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=existing_run)
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

        await job_integrate.original_func(str(ws_id), str(existing_run.id))

    mock_run_repo.create.assert_not_called()
    mock_run_repo.get_by_id.assert_awaited_once_with(existing_run.id)
    mock_run_repo.update_status.assert_awaited_once()
    mock_run_repo.update_counters.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_integrate_marks_existing_run_failed_when_engine_raises() -> None:
    """job_integrate should persist failure on the supplied IntegratorRun in a separate transaction."""
    ws_id = uuid.uuid4()
    existing_run = MagicMock()
    existing_run.id = uuid.uuid4()
    existing_run.workspace_id = ws_id

    mock_engine_instance = AsyncMock()
    mock_engine_instance.run = AsyncMock(side_effect=RuntimeError("boom"))

    main_run_repo = AsyncMock()
    main_run_repo.create = AsyncMock()
    main_run_repo.get_by_id = AsyncMock(return_value=existing_run)
    main_run_repo.update_status = AsyncMock()
    main_run_repo.update_counters = AsyncMock()

    failure_run_repo = AsyncMock()
    failure_run_repo.update_status = AsyncMock()

    main_session = AsyncMock()
    main_session.__aenter__ = AsyncMock(return_value=main_session)
    main_session.__aexit__ = AsyncMock(return_value=False)
    main_session.begin = MagicMock()
    main_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    main_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    main_session.execute = AsyncMock()

    failure_session = AsyncMock()
    failure_session.__aenter__ = AsyncMock(return_value=failure_session)
    failure_session.__aexit__ = AsyncMock(return_value=False)
    failure_session.begin = MagicMock()
    failure_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    failure_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    failure_session.execute = AsyncMock()

    mock_factory = MagicMock(side_effect=[main_session, failure_session])
    mock_set_workspace_context = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks.IntegratorEngine", return_value=mock_engine_instance),
        patch(
            "alayaos_core.worker.tasks.IntegratorRunRepository",
            side_effect=[main_run_repo, failure_run_repo],
        ),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=mock_set_workspace_context),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks.EntityCacheService"),
        patch("alayaos_core.worker.tasks.EntityRepository"),
        patch("alayaos_core.worker.tasks.ClaimRepository"),
        patch("alayaos_core.worker.tasks.RelationRepository"),
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_integrate

        with pytest.raises(RuntimeError, match="boom"):
            await job_integrate.original_func(str(ws_id), str(existing_run.id))

    main_run_repo.create.assert_not_called()
    main_run_repo.get_by_id.assert_awaited_once_with(existing_run.id)
    main_run_repo.update_status.assert_not_called()
    main_run_repo.update_counters.assert_not_called()
    failure_run_repo.update_status.assert_awaited_once_with(existing_run.id, "failed", error_message="boom")
    assert mock_set_workspace_context.await_count == 2


@pytest.mark.asyncio
async def test_job_integrate_marks_auto_created_run_failed_when_engine_raises() -> None:
    """job_integrate should commit auto-created runs before processing so failures remain observable."""
    ws_id = uuid.uuid4()
    auto_run = MagicMock()
    auto_run.id = uuid.uuid4()
    auto_run.workspace_id = ws_id

    mock_engine_instance = AsyncMock()
    mock_engine_instance.run = AsyncMock(side_effect=RuntimeError("boom"))

    create_run_repo = AsyncMock()
    create_run_repo.create = AsyncMock(return_value=auto_run)

    main_run_repo = AsyncMock()
    main_run_repo.get_by_id = AsyncMock(return_value=auto_run)
    main_run_repo.update_status = AsyncMock()
    main_run_repo.update_counters = AsyncMock()

    failure_run_repo = AsyncMock()
    failure_run_repo.update_status = AsyncMock()

    create_session = AsyncMock()
    create_session.__aenter__ = AsyncMock(return_value=create_session)
    create_session.__aexit__ = AsyncMock(return_value=False)
    create_session.begin = MagicMock()
    create_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    create_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    create_session.execute = AsyncMock()

    main_session = AsyncMock()
    main_session.__aenter__ = AsyncMock(return_value=main_session)
    main_session.__aexit__ = AsyncMock(return_value=False)
    main_session.begin = MagicMock()
    main_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    main_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    main_session.execute = AsyncMock()

    failure_session = AsyncMock()
    failure_session.__aenter__ = AsyncMock(return_value=failure_session)
    failure_session.__aexit__ = AsyncMock(return_value=False)
    failure_session.begin = MagicMock()
    failure_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    failure_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    failure_session.execute = AsyncMock()

    mock_factory = MagicMock(side_effect=[create_session, main_session, failure_session])
    mock_set_workspace_context = AsyncMock()

    with (
        patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
        patch("alayaos_core.worker.tasks.IntegratorEngine", return_value=mock_engine_instance),
        patch(
            "alayaos_core.worker.tasks.IntegratorRunRepository",
            side_effect=[create_run_repo, main_run_repo, failure_run_repo],
        ),
        patch("alayaos_core.worker.tasks._set_workspace_context", new=mock_set_workspace_context),
        patch("alayaos_core.worker.tasks.aioredis") as mock_aioredis,
        patch("alayaos_core.worker.tasks.EntityCacheService"),
        patch("alayaos_core.worker.tasks.EntityRepository"),
        patch("alayaos_core.worker.tasks.ClaimRepository"),
        patch("alayaos_core.worker.tasks.RelationRepository"),
    ):
        mock_aioredis.from_url.return_value = AsyncMock()
        mock_aioredis.from_url.return_value.aclose = AsyncMock()

        from alayaos_core.worker.tasks import job_integrate

        with pytest.raises(RuntimeError, match="boom"):
            await job_integrate.original_func(str(ws_id))

    create_run_repo.create.assert_awaited_once()
    create_kwargs = create_run_repo.create.await_args.kwargs
    assert create_kwargs["workspace_id"] == ws_id
    assert create_kwargs["trigger"] == "job_integrate"
    assert create_kwargs["scope_description"] == "dirty_set + 48h window"
    assert create_kwargs["llm_model"]
    main_run_repo.get_by_id.assert_awaited_once_with(auto_run.id)
    main_run_repo.update_status.assert_not_called()
    main_run_repo.update_counters.assert_not_called()
    failure_run_repo.update_status.assert_awaited_once_with(auto_run.id, "failed", error_message="boom")
    assert mock_set_workspace_context.await_count == 3


@pytest.mark.asyncio
async def test_job_integrate_writes_phase_traces_and_calls_recalc() -> None:
    """job_integrate writes PipelineTrace for each phase_usage and calls recalc_usage."""
    from alayaos_core.extraction.integrator.schemas import IntegratorPhaseUsage, IntegratorRunResult
    from alayaos_core.llm.interface import LLMUsage

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    phase_usage = IntegratorPhaseUsage(
        stage="integrator:panoramic",
        pass_number=1,
        usage=LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.001),
        duration_ms=200,
        details={"applied_actions": 3},
    )

    engine_result = IntegratorRunResult(
        status="completed",
        entities_scanned=5,
        entities_deduplicated=1,
        phase_usages=[phase_usage],
        tokens_used=150,
        cost_usd=0.001,
    )

    mock_run = MagicMock()
    mock_run.id = run_id

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock(return_value=mock_run)
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.recalc_usage = AsyncMock()

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock(return_value=MagicMock())

    mock_engine = AsyncMock()
    mock_engine.run = AsyncMock(return_value=engine_result)

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
        patch("alayaos_core.worker.tasks.IntegratorEngine", return_value=mock_engine),
        patch("alayaos_core.worker.tasks.IntegratorRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.worker.tasks.PipelineTraceRepository", return_value=mock_trace_repo),
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

    # PipelineTraceRepository must have been called for each phase_usage
    assert mock_trace_repo.create.await_count >= 1, "PipelineTraceRepository.create not called for phase_usages"

    # Verify the trace was written with integrator_run_id and granular token fields
    trace_kwargs = mock_trace_repo.create.call_args_list[0].kwargs
    assert trace_kwargs.get("integrator_run_id") == run_id, f"integrator_run_id not set: {trace_kwargs}"
    assert "tokens_in" in trace_kwargs, "tokens_in not passed to trace_repo.create"
    assert "tokens_out" in trace_kwargs, "tokens_out not passed to trace_repo.create"

    # recalc_usage must be called after writing traces
    mock_run_repo.recalc_usage.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
async def test_job_integrate_uses_error_message_for_failed_status() -> None:
    """job_integrate uses result.error_message (not result.reason) for status=failed."""
    from alayaos_core.extraction.integrator.schemas import IntegratorRunResult

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    engine_result = IntegratorRunResult(
        status="failed",
        error_message="RuntimeError: panoramic phase exploded",
        phase_usages=[],
    )

    mock_run = MagicMock()
    mock_run.id = run_id

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock(return_value=mock_run)
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.recalc_usage = AsyncMock()

    mock_trace_repo = AsyncMock()
    mock_trace_repo.create = AsyncMock(return_value=MagicMock())

    mock_engine = AsyncMock()
    mock_engine.run = AsyncMock(return_value=engine_result)

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
        patch("alayaos_core.worker.tasks.IntegratorEngine", return_value=mock_engine),
        patch("alayaos_core.worker.tasks.IntegratorRunRepository", return_value=mock_run_repo),
        patch("alayaos_core.worker.tasks.PipelineTraceRepository", return_value=mock_trace_repo),
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

    # update_status must use error_message from result (not result.reason)
    status_call_args = mock_run_repo.update_status.call_args_list
    assert len(status_call_args) >= 1
    call = status_call_args[0]
    assert call.kwargs.get("status") == "failed" or call.args[1] == "failed"
    error_msg = call.kwargs.get("error_message") or (call.args[2] if len(call.args) > 2 else None)
    assert error_msg is not None and "panoramic phase exploded" in error_msg
