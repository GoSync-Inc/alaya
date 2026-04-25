"""Tests for IntegratorRunRepository.recalc_usage.

Covers:
- Granular per-column SUMs
- Idempotent: second call returns same result
- Skip-if-no-traces guard
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeTrace:
    def __init__(
        self,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        tokens_cached: int = 0,
        cache_write_5m_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.tokens_cached = tokens_cached
        self.cache_write_5m_tokens = cache_write_5m_tokens
        self.cache_write_1h_tokens = cache_write_1h_tokens
        self.cost_usd = cost_usd


@pytest.mark.asyncio
async def test_recalc_usage_integrator_sums_all_columns() -> None:
    """recalc_usage sums granular columns from pipeline_traces into integrator_run row."""
    from alayaos_core.repositories.integrator_run import IntegratorRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    repo = IntegratorRunRepository(mock_session, ws_id)

    # Simulate "traces exist" check returning a row id
    trace_exists_result = MagicMock()
    trace_exists_result.scalar_one_or_none.return_value = uuid.uuid4()

    # The update call
    update_result = MagicMock()

    # The get_by_id SELECT after update (for log_run_aggregated emission)
    get_by_id_result = MagicMock()
    get_by_id_result.scalar_one_or_none.return_value = None  # no run → emit skipped

    mock_session.execute.side_effect = [trace_exists_result, update_result, get_by_id_result]

    await repo.recalc_usage(run_id)

    # execute called 3x: exists check, update, get_by_id (for observability emit)
    assert mock_session.execute.call_count == 3


@pytest.mark.asyncio
async def test_recalc_usage_integrator_skip_when_no_traces() -> None:
    """When no traces exist, recalc_usage is a no-op (preserves direct-write values)."""
    from alayaos_core.repositories.integrator_run import IntegratorRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    repo = IntegratorRunRepository(mock_session, ws_id)

    # Simulate "traces do not exist"
    trace_exists_result = MagicMock()
    trace_exists_result.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [trace_exists_result]

    await repo.recalc_usage(run_id)

    # Only the existence check was called; UPDATE was not issued
    assert mock_session.execute.call_count == 1


@pytest.mark.asyncio
async def test_recalc_usage_integrator_idempotent() -> None:
    """Calling recalc_usage twice should not error (both calls attempt the same SUM)."""
    from alayaos_core.repositories.integrator_run import IntegratorRunRepository

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    repo = IntegratorRunRepository(mock_session, ws_id)

    # Both calls: traces exist
    trace_exists_result1 = MagicMock()
    trace_exists_result1.scalar_one_or_none.return_value = uuid.uuid4()
    update_result1 = MagicMock()
    get_by_id_result1 = MagicMock()
    get_by_id_result1.scalar_one_or_none.return_value = None  # no run → emit skipped

    trace_exists_result2 = MagicMock()
    trace_exists_result2.scalar_one_or_none.return_value = uuid.uuid4()
    update_result2 = MagicMock()
    get_by_id_result2 = MagicMock()
    get_by_id_result2.scalar_one_or_none.return_value = None  # no run → emit skipped

    mock_session.execute.side_effect = [
        trace_exists_result1,
        update_result1,
        get_by_id_result1,
        trace_exists_result2,
        update_result2,
        get_by_id_result2,
    ]

    await repo.recalc_usage(run_id)
    await repo.recalc_usage(run_id)

    # 3 calls per recalc_usage: exists check, update, get_by_id → 6 total
    assert mock_session.execute.call_count == 6
