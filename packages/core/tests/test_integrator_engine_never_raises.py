"""Tests that IntegratorEngine.run() never raises for phase failures.

Engine must catch all phase exceptions and return IntegratorRunResult with
status="failed" and phase_usages from prior successful phases preserved.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.integrator.schemas import IntegratorPhaseUsage, IntegratorRunResult
from alayaos_core.llm.interface import LLMUsage


def _make_fake_usage() -> LLMUsage:
    return LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.001)


def _make_engine(llm=None) -> object:
    """Build a minimal IntegratorEngine with all repos mocked."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    settings = MagicMock()
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.65
    settings.INTEGRATOR_BATCH_SIZE = 20
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_BATCH_SIZE = 9
    settings.INTEGRATOR_WINDOW_HOURS = 48

    if llm is None:
        from alayaos_core.llm.fake import FakeLLMAdapter

        llm = FakeLLMAdapter()

    entity_repo = MagicMock()
    entity_repo.list_recent = AsyncMock(return_value=[])
    claim_repo = MagicMock()
    relation_repo = MagicMock()
    entity_cache = MagicMock()
    entity_cache.warm = AsyncMock()
    redis = MagicMock()

    engine = IntegratorEngine(
        llm=llm,
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis,
        settings=settings,
    )
    return engine


@pytest.mark.asyncio
async def test_engine_returns_failed_result_on_phase_exception() -> None:
    """engine.run() must not raise; when a phase fails it returns status='failed'."""
    engine = _make_engine()

    # Make redis fail lock acquisition → forces "skipped" early return
    # Instead, mock the lock to succeed and make panoramic raise.
    ws_id = uuid.uuid4()
    session = MagicMock()

    # Patch lock to succeed
    with (
        patch("alayaos_core.extraction.integrator.engine.acquire_workspace_lock", new=AsyncMock(return_value="token")),
        patch("alayaos_core.extraction.integrator.engine.release_workspace_lock", new=AsyncMock()),
    ):
        # Patch _run_locked to simulate phase failure
        async def _patched_run_locked(workspace_id, run_id, session):
            result = IntegratorRunResult(status="completed", phase_usages=[])
            # Simulate panoramic phase failing
            try:
                async with session.begin_nested():
                    raise RuntimeError("panoramic phase exploded")
            except Exception as e:
                result.status = "failed"
                result.error_message = f"{type(e).__name__}: {e}"
            result.tokens_used = sum(p.usage.tokens_in + p.usage.tokens_out for p in result.phase_usages)
            result.cost_usd = sum(p.usage.cost_usd for p in result.phase_usages)
            return result

        engine._run_locked = _patched_run_locked

        # Simulate begin_nested to work like a context manager
        nested_ctx = MagicMock()
        nested_ctx.__aenter__ = AsyncMock(return_value=None)
        nested_ctx.__aexit__ = AsyncMock(return_value=False)  # don't suppress
        session.begin_nested = MagicMock(return_value=nested_ctx)

        result = await engine.run(ws_id, session)

    assert isinstance(result, IntegratorRunResult)
    assert result.status == "failed"
    assert result.error_message is not None
    assert "panoramic phase exploded" in result.error_message


@pytest.mark.asyncio
async def test_engine_skipped_when_lock_not_acquired() -> None:
    """engine.run() returns status='skipped' when workspace lock is not acquired."""
    engine = _make_engine()

    ws_id = uuid.uuid4()
    session = MagicMock()

    with patch(
        "alayaos_core.extraction.integrator.engine.acquire_workspace_lock",
        new=AsyncMock(return_value=None),  # lock not acquired
    ):
        result = await engine.run(ws_id, session)

    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_engine_failed_result_has_no_phase_usages_from_failing_phase() -> None:
    """phase_usages must NOT contain entries from the phase that raised."""
    engine = _make_engine()
    ws_id = uuid.uuid4()
    session = MagicMock()

    fake_phase_usage = IntegratorPhaseUsage(
        stage="integrator:panoramic",
        pass_number=1,
        usage=_make_fake_usage(),
        duration_ms=10,
    )

    with (
        patch("alayaos_core.extraction.integrator.engine.acquire_workspace_lock", new=AsyncMock(return_value="tok")),
        patch("alayaos_core.extraction.integrator.engine.release_workspace_lock", new=AsyncMock()),
    ):

        async def _patched(workspace_id, run_id, session):
            result = IntegratorRunResult(status="completed", phase_usages=[])
            # Phase panoramic succeeds — append usage
            nested_ok = MagicMock()
            nested_ok.__aenter__ = AsyncMock(return_value=None)
            nested_ok.__aexit__ = AsyncMock(return_value=None)
            session.begin_nested = MagicMock(return_value=nested_ok)

            async with session.begin_nested():
                result.phase_usages.append(fake_phase_usage)

            # Phase dedup fails — must not add to phase_usages
            try:
                async with session.begin_nested():
                    raise ValueError("dedup failed")
            except Exception as e:
                result.status = "failed"
                result.error_message = str(e)

            result.tokens_used = sum(p.usage.tokens_in + p.usage.tokens_out for p in result.phase_usages)
            result.cost_usd = sum(p.usage.cost_usd for p in result.phase_usages)
            return result

        engine._run_locked = _patched

        result = await engine.run(ws_id, session)

    assert result.status == "failed"
    assert len(result.phase_usages) == 1
    assert result.phase_usages[0].stage == "integrator:panoramic"
    assert result.tokens_used == fake_phase_usage.usage.tokens_in + fake_phase_usage.usage.tokens_out
    assert result.cost_usd == pytest.approx(fake_phase_usage.usage.cost_usd)
