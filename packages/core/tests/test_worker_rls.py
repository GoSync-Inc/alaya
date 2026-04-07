"""Tests that worker jobs set RLS workspace context correctly."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_set_workspace_context_uses_parameterized_query():
    """_set_workspace_context must use parameterized text() query, not interpolation."""
    from alayaos_core.worker.tasks import _set_workspace_context

    session = AsyncMock()
    workspace_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    await _set_workspace_context(session, workspace_id)

    assert session.execute.call_count == 1
    args, _ = session.execute.call_args
    sql_clause = args[0]
    # Must be a SQLAlchemy text() clause, not raw string
    assert hasattr(sql_clause, "text"), "Expected sqlalchemy text() clause"
    assert "SET LOCAL app.workspace_id" in sql_clause.text
    assert ":wid" in sql_clause.text
    # Params passed separately (not interpolated)
    params = args[1]
    assert params == {"wid": workspace_id}


@pytest.mark.asyncio
async def test_set_workspace_context_is_called_for_different_workspaces():
    """_set_workspace_context passes workspace_id correctly to the query."""
    from alayaos_core.worker.tasks import _set_workspace_context

    for wid in [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]:
        session = AsyncMock()
        await _set_workspace_context(session, wid)
        _, args, _ = session.execute.mock_calls[0]
        assert args[1] == {"wid": wid}


@pytest.mark.asyncio
async def test_job_write_calls_rls_context():
    """job_write must call _set_workspace_context with correct workspace_id."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = "44444444-4444-4444-4444-444444444444"
    extraction_run_id = "55555555-5555-5555-5555-555555555555"

    rls_calls: list[str] = []
    original = worker_tasks._set_workspace_context

    async def mock_rls(session, wid: str) -> None:
        rls_calls.append(wid)

    worker_tasks._set_workspace_context = mock_rls  # type: ignore[assignment]

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    mock_factory_inst = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )
    mock_factory = MagicMock(return_value=mock_factory_inst)

    try:
        with (
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.extraction.pipeline.run_write", new_callable=AsyncMock, return_value=None),
            patch("alayaos_core.worker.tasks.Settings", MagicMock(return_value=MagicMock(ANTHROPIC_API_KEY=MagicMock(get_secret_value=lambda: "")))),
        ):
            await worker_tasks.job_write.original_func(extraction_run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original  # type: ignore[assignment]

    assert workspace_id in rls_calls


@pytest.mark.asyncio
async def test_job_enrich_calls_rls_context():
    """job_enrich must call _set_workspace_context with correct workspace_id."""
    from alayaos_core.worker import tasks as worker_tasks

    workspace_id = "66666666-6666-6666-6666-666666666666"
    extraction_run_id = "77777777-7777-7777-7777-777777777777"

    rls_calls: list[str] = []
    original = worker_tasks._set_workspace_context

    async def mock_rls(session, wid: str) -> None:
        rls_calls.append(wid)

    worker_tasks._set_workspace_context = mock_rls  # type: ignore[assignment]

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    mock_factory_inst = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )
    mock_factory = MagicMock(return_value=mock_factory_inst)

    try:
        with (
            patch("alayaos_core.worker.tasks._session_factory", return_value=mock_factory),
            patch("alayaos_core.extraction.pipeline.run_enrich", new_callable=AsyncMock, return_value=None),
        ):
            await worker_tasks.job_enrich.original_func(extraction_run_id, workspace_id)
    finally:
        worker_tasks._set_workspace_context = original  # type: ignore[assignment]

    assert workspace_id in rls_calls
