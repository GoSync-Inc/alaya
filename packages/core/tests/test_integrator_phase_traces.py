"""Tests that IntegratorEngine phase usages are persisted as PipelineTrace rows.

Verifies:
- phase trace rows have integrator_run_id set
- phase trace rows have event_id=None (integrator traces are not event-scoped)
- granular token fields are passed (tokens_in, tokens_out)
- one trace per phase_usage entry
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.integrator.schemas import IntegratorPhaseUsage, IntegratorRunResult
from alayaos_core.llm.interface import LLMUsage


def _make_usage(tokens_in: int = 10, tokens_out: int = 5) -> LLMUsage:
    return LLMUsage(tokens_in=tokens_in, tokens_out=tokens_out, tokens_cached=0, cost_usd=0.001)


def _make_run_result_with_phases() -> IntegratorRunResult:
    return IntegratorRunResult(
        status="completed",
        phase_usages=[
            IntegratorPhaseUsage(
                stage="integrator:panoramic",
                pass_number=1,
                usage=_make_usage(tokens_in=20, tokens_out=8),
                duration_ms=150,
            ),
            IntegratorPhaseUsage(
                stage="integrator:dedup",
                pass_number=1,
                usage=_make_usage(tokens_in=30, tokens_out=12),
                duration_ms=200,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_phase_traces_written_with_integrator_run_id() -> None:
    """job_integrate writes one PipelineTrace per phase_usage, with integrator_run_id set."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    engine_result = _make_run_result_with_phases()

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

    # One trace per phase_usage
    assert mock_trace_repo.create.await_count == len(engine_result.phase_usages), (
        f"Expected {len(engine_result.phase_usages)} trace.create calls, got {mock_trace_repo.create.await_count}"
    )

    for i, phase in enumerate(engine_result.phase_usages):
        call_kwargs = mock_trace_repo.create.call_args_list[i].kwargs
        assert call_kwargs.get("integrator_run_id") == run_id, f"Phase {i}: integrator_run_id not set in trace kwargs"
        # event_id must NOT be passed (or must be None/absent — integrator traces are not event-scoped)
        event_id_val = call_kwargs.get("event_id")
        assert event_id_val is None, f"Phase {i}: event_id should be None for integrator traces, got {event_id_val!r}"
        assert call_kwargs.get("tokens_in") == phase.usage.tokens_in
        assert call_kwargs.get("tokens_out") == phase.usage.tokens_out
        assert call_kwargs.get("stage") == phase.stage
        # C1: workspace_id must be passed so the repository can attach it to the trace
        assert call_kwargs.get("workspace_id") == ws_id, (
            f"Phase {i}: workspace_id not passed to PipelineTraceRepository.create; "
            f"got kwargs: {list(call_kwargs.keys())}"
        )


@pytest.mark.asyncio
async def test_phase_traces_recalc_usage_called_after_writes() -> None:
    """recalc_usage is called after all phase traces are written."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    engine_result = _make_run_result_with_phases()

    mock_run = MagicMock()
    mock_run.id = run_id

    mock_run_repo = AsyncMock()
    mock_run_repo.create = AsyncMock(return_value=mock_run)
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run)
    mock_run_repo.update_status = AsyncMock()
    mock_run_repo.update_counters = AsyncMock()
    mock_run_repo.recalc_usage = AsyncMock()

    mock_trace_repo = AsyncMock()
    call_order: list[str] = []

    async def trace_create(**kwargs):
        call_order.append("trace.create")
        return MagicMock()

    async def recalc(run_id):
        call_order.append("recalc_usage")

    mock_trace_repo.create = AsyncMock(side_effect=trace_create)
    mock_run_repo.recalc_usage = AsyncMock(side_effect=recalc)

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

    # recalc must come after all trace writes
    recalc_index = call_order.index("recalc_usage")
    trace_indices = [i for i, v in enumerate(call_order) if v == "trace.create"]
    assert trace_indices, "No trace.create calls recorded"
    assert all(i < recalc_index for i in trace_indices), "recalc_usage called before some trace writes"


@pytest.mark.asyncio
async def test_phase_traces_skipped_when_no_phase_usages() -> None:
    """When phase_usages is empty, no traces are written and recalc_usage is still called."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    engine_result = IntegratorRunResult(status="completed", phase_usages=[])

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

    # No trace writes when phase_usages is empty
    assert mock_trace_repo.create.await_count == 0
    # recalc_usage still called
    mock_run_repo.recalc_usage.assert_awaited_once()
