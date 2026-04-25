"""Tests for recalc_usage on a failed integrator run.

Simulates: phase A succeeds (writes trace), phase B raises.
Worker writes the phase A trace and calls recalc_usage.
The integrator_runs row should reflect only phase A cost.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_recalc_usage_failed_run_reflects_phase_a_cost() -> None:
    """After a partial failure (phase B raises), recalc_usage sums phase A trace only."""
    from alayaos_core.repositories.integrator_run import IntegratorRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    repo = IntegratorRunRepository(mock_session, ws_id)

    # Traces exist (phase A trace was written before failure)
    trace_exists_result = MagicMock()
    trace_exists_result.scalar_one_or_none.return_value = uuid.uuid4()
    update_result = MagicMock()

    # The get_by_id SELECT after update (for log_run_aggregated emission)
    get_by_id_result = MagicMock()
    get_by_id_result.scalar_one_or_none.return_value = None  # no run → emit skipped

    mock_session.execute.side_effect = [trace_exists_result, update_result, get_by_id_result]

    # Should not raise even for a "failed" run
    await repo.recalc_usage(run_id)

    # UPDATE was issued — recalc_usage is symmetric for completed and failed runs
    # 3 calls: exists check, update, get_by_id (for observability emit)
    assert mock_session.execute.call_count == 3


@pytest.mark.asyncio
async def test_recalc_usage_failed_run_no_traces_skips() -> None:
    """If phase A also failed (no traces written), recalc_usage skips the UPDATE."""
    from alayaos_core.repositories.integrator_run import IntegratorRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    repo = IntegratorRunRepository(mock_session, ws_id)

    trace_exists_result = MagicMock()
    trace_exists_result.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [trace_exists_result]

    await repo.recalc_usage(run_id)

    assert mock_session.execute.call_count == 1
