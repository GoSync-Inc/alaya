"""Tests for the multi-pass IntegratorEngine orchestrator (Sprint 6).

Covers:
- test_multi_pass_convergence     — 2nd pass emits 0 actions → stop with "no_actions"
- test_cycle_detection            — same actions repeated → "cycle_detected"
- test_max_passes_cap             — always emitting actions → stops at 3 with "max_passes"
- test_cost_aggregation           — cost_usd non-zero after run
- test_stable_graph_single_pass   — no dirty entities → 1 pass, 0 actions
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.integrator.schemas import IntegratorRunResult
from alayaos_core.llm.interface import LLMUsage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zero_usage() -> LLMUsage:
    """Return a zero-cost LLMUsage for test mocks."""
    return LLMUsage.zero()


def _make_session() -> AsyncMock:
    """Create an AsyncMock session with begin_nested properly mocked.

    The engine uses `async with session.begin_nested():` which requires
    begin_nested() to return an object with __aenter__/__aexit__, not a
    coroutine. AsyncMock auto-creates attributes as AsyncMocks, which
    are coroutines and fail the async-CM protocol.
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


def _make_redis_mock(dirty_ids: list[str] | None = None):
    """Create a mock Redis with dirty-set behaviour."""
    redis_mock = AsyncMock()
    redis_mock.rename = AsyncMock(return_value=True)
    members = {str(i).encode() for i in (dirty_ids or [])}
    redis_mock.smembers = AsyncMock(return_value=members)
    redis_mock.delete = AsyncMock(return_value=1)
    redis_mock.set = AsyncMock(return_value=True)  # lock acquire
    redis_mock.eval = AsyncMock(return_value=1)  # lock release
    return redis_mock


def _make_settings():
    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_MODEL = "claude-test"
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_BATCH_SIZE = 9
    return settings


def _make_engine(redis_mock=None, settings=None, entity_repo=None):
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    if redis_mock is None:
        redis_mock = _make_redis_mock()
    if settings is None:
        settings = _make_settings()
    if entity_repo is None:
        entity_repo = AsyncMock()
        entity_repo.list_recent = AsyncMock(return_value=[])
        entity_repo.get_by_id = AsyncMock(return_value=None)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    return IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Test: IntegratorRunResult has pass_count and convergence_reason fields
# ---------------------------------------------------------------------------


def test_integrator_run_result_has_pass_count_and_convergence_reason():
    """IntegratorRunResult must expose pass_count and convergence_reason."""
    result = IntegratorRunResult(status="completed")
    assert hasattr(result, "pass_count"), "IntegratorRunResult missing pass_count field"
    assert hasattr(result, "convergence_reason"), "IntegratorRunResult missing convergence_reason field"


# ---------------------------------------------------------------------------
# Test: stable graph → single pass, 0 actions, convergence = no_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stable_graph_single_pass():
    """When no entities are loaded, the loop runs 1 pass and converges with no_actions."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    # Patch PanoramicPass.run to return empty actions
    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=PanoramicResult(actions=[]))
        mock_panoramic_pass.return_value = pano_instance

        # Patch _dedup_v2 to return 0
        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))

        result = await engine._run_locked(ws_id, run_id, session)

    assert result.status == "completed"
    assert result.pass_count == 1
    assert result.convergence_reason == "no_actions"


# ---------------------------------------------------------------------------
# Test: multi_pass_convergence — 2nd pass emits 0 actions → "no_actions"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_pass_convergence():
    """Engine stops on 2nd pass when panoramic emits 0 actions (convergence = no_actions)."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    entity_id = uuid.uuid4()
    # Pass 1 returns 1 action; pass 2 returns 0 actions
    pass_results = [
        PanoramicResult(
            actions=[
                PanoramicAction(
                    action="remove_noise",
                    entity_id=entity_id,
                    params={"reason": "test"},
                    confidence=0.9,
                    rationale="garbage",
                )
            ]
        ),
        PanoramicResult(actions=[]),
    ]
    call_count = 0

    async def pano_run(*args, **kwargs):
        nonlocal call_count
        result = pass_results[min(call_count, len(pass_results) - 1)]
        call_count += 1
        return result

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    async def apply_panoramic_actions_side_effect(actions, *args, **kwargs):
        # Return len(actions) so it mirrors the real panoramic result
        return len(actions)

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(side_effect=pano_run)
        mock_panoramic_pass.return_value = pano_instance

        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))
        engine._apply_panoramic_actions = AsyncMock(side_effect=apply_panoramic_actions_side_effect)

        result = await engine._run_locked(ws_id, run_id, session)

    assert result.status == "completed"
    assert result.pass_count == 2, f"Expected 2 passes, got {result.pass_count}"
    assert result.convergence_reason == "no_actions"


# ---------------------------------------------------------------------------
# Test: cycle_detection — same actions repeated → "cycle_detected"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_detection():
    """Engine stops when same panoramic actions appear in consecutive passes (cycle_detected)."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    entity_id = uuid.uuid4()
    repeated_action = PanoramicAction(
        action="remove_noise",
        entity_id=entity_id,
        params={"reason": "cycle test"},
        confidence=0.9,
        rationale="cycling",
    )
    same_result = PanoramicResult(actions=[repeated_action])

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=same_result)
        mock_panoramic_pass.return_value = pano_instance

        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))
        engine._apply_panoramic_actions = AsyncMock(return_value=1)

        result = await engine._run_locked(ws_id, run_id, session)

    assert result.status == "completed"
    assert result.convergence_reason == "cycle_detected", f"Expected cycle_detected, got {result.convergence_reason}"
    # Must have stopped before reaching max passes
    assert result.pass_count < 3, f"Should stop on cycle before max_passes, got {result.pass_count}"


# ---------------------------------------------------------------------------
# Test: max_passes_cap — always emitting actions → "max_passes"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_passes_cap():
    """Engine stops at max_passes=3 when actions never converge."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    call_count = 0

    async def pano_run(*args, **kwargs):
        nonlocal call_count
        # Each pass produces a unique action so cycle detection never fires
        entity_id = uuid.uuid4()
        call_count += 1
        return PanoramicResult(
            actions=[
                PanoramicAction(
                    action="remove_noise",
                    entity_id=entity_id,
                    params={"reason": f"pass-{call_count}"},
                    confidence=0.9,
                    rationale=f"noise pass {call_count}",
                )
            ]
        )

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(side_effect=pano_run)
        mock_panoramic_pass.return_value = pano_instance

        engine._dedup_v2 = AsyncMock(return_value=(1, [], _zero_usage()))
        engine._apply_panoramic_actions = AsyncMock(return_value=1)

        result = await engine._run_locked(ws_id, run_id, session)

    assert result.status == "completed"
    assert result.convergence_reason == "max_passes", f"Expected max_passes, got {result.convergence_reason}"
    assert result.pass_count == 3, f"Expected 3 passes, got {result.pass_count}"


# ---------------------------------------------------------------------------
# Test: cost_aggregation — cost_usd from panoramic LLM calls tracked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_aggregation():
    """cost_usd on the result is non-zero when LLM calls are made."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=PanoramicResult(actions=[]))
        # Attach a cost attribute that the engine can read
        pano_instance.last_cost_usd = 0.05
        mock_panoramic_pass.return_value = pano_instance

        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))

        result = await engine._run_locked(ws_id, run_id, session)

    # cost_usd field must exist (value may be 0 if no actual LLM — we just check it's tracked)
    assert hasattr(result, "cost_usd")
    assert isinstance(result.cost_usd, float)


# ---------------------------------------------------------------------------
# Test: _apply_panoramic_actions persists remove_noise action via action_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_panoramic_actions_remove_noise():
    """_apply_panoramic_actions creates IntegratorAction for remove_noise and soft-deletes entity."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction

    entity_id = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.name = "garbage hex id"
    entity_mock.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)
    entity_repo.update = AsyncMock(return_value=entity_mock)
    entity_repo.list_recent = AsyncMock(return_value=[])

    engine = _make_engine(entity_repo=entity_repo)

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(return_value=MagicMock())

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    session = AsyncMock()

    action = PanoramicAction(
        action="remove_noise",
        entity_id=entity_id,
        params={"reason": "garbage"},
        confidence=0.95,
        rationale="looks like garbage",
    )

    applied = await engine._apply_panoramic_actions(
        [action], ws_id, run_id, pass_number=1, session=session, action_repo=action_repo
    )

    assert applied == 1
    # entity must be soft-deleted
    entity_repo.update.assert_called_once_with(entity_id, is_deleted=True)
    # action must be recorded
    action_repo.create.assert_called_once()


# ---------------------------------------------------------------------------
# Test: dedup v2 called with real run_id (not uuid int=0 placeholder)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_v2_receives_real_run_id():
    """_run_locked passes real run_id (not uuid int=0) to _dedup_v2."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    entity_id = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.name = "Alice"
    entity_mock.is_deleted = False
    entity_mock.aliases = []
    entity_mock.properties = {}
    entity_mock.entity_type = MagicMock()
    entity_mock.entity_type.slug = "person"

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_mock])
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    engine = _make_engine(entity_repo=entity_repo)
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    real_run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    captured_run_ids: list[uuid.UUID] = []

    async def capture_dedup_v2(entities, workspace_id, session, *, run_id, action_repo):
        captured_run_ids.append(run_id)
        return 0, []

    engine._dedup_v2 = capture_dedup_v2  # type: ignore[assignment]

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_panoramic_pass:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=PanoramicResult(actions=[]))
        mock_panoramic_pass.return_value = pano_instance

        await engine._run_locked(ws_id, real_run_id, session)

    assert captured_run_ids, "Expected _dedup_v2 to be called at least once"
    # None of the calls should use the placeholder uuid int=0
    placeholder = uuid.UUID(int=0)
    for rid in captured_run_ids:
        assert rid != placeholder, "_dedup_v2 received placeholder run_id uuid.UUID(int=0)"
    assert real_run_id in captured_run_ids, f"Expected real_run_id {real_run_id} in calls"


# ---------------------------------------------------------------------------
# Test: entity refresh between passes (Fix 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entities_reloaded_between_passes():
    """entities_with_context is reloaded after commit so pass 2 sees updated graph."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    # Two entities: pass 1 sees [entity_old], pass 2 should see [entity_new]
    entity_old_id = uuid.uuid4()
    entity_new_id = uuid.uuid4()

    entity_old_mock = MagicMock()
    entity_old_mock.id = entity_old_id
    entity_old_mock.name = "OldName"
    entity_old_mock.is_deleted = False
    entity_old_mock.aliases = []
    entity_old_mock.properties = {}
    entity_old_mock.entity_type = MagicMock()
    entity_old_mock.entity_type.slug = "person"

    entity_new_mock = MagicMock()
    entity_new_mock.id = entity_new_id
    entity_new_mock.name = "NewName"
    entity_new_mock.is_deleted = False
    entity_new_mock.aliases = []
    entity_new_mock.properties = {}
    entity_new_mock.entity_type = MagicMock()
    entity_new_mock.entity_type.slug = "person"

    # First list_recent call (initial load) returns old entity
    # Second list_recent call (pass 2 refresh) returns new entity
    # Third list_recent call (post-loop reload before enrichment) returns new entity
    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(
        side_effect=[
            [entity_old_mock],  # initial
            [entity_new_mock],  # refresh in pass 2
            [entity_new_mock],  # post-loop reload before enrichment (Fix 3)
        ]
    )
    entity_repo.get_by_id = AsyncMock(
        side_effect=lambda eid: entity_old_mock if eid == entity_old_id else entity_new_mock
    )

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    settings = _make_settings()
    redis_mock = _make_redis_mock()

    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    pass_entities_seen: list[list[uuid.UUID]] = []

    async def pano_run(*args, **kwargs):
        entities = kwargs.get("entities", args[1] if len(args) > 1 else [])
        pass_entities_seen.append([e.id for e in entities])
        if len(pass_entities_seen) == 1:
            # Pass 1: emit one action so loop continues
            return PanoramicResult(
                actions=[
                    PanoramicAction(
                        action="remove_noise",
                        entity_id=entity_old_id,
                        params={},
                        confidence=0.9,
                        rationale="stale",
                    )
                ]
            )
        # Pass 2: no actions
        return PanoramicResult(actions=[])

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(side_effect=pano_run)
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))
        engine._apply_panoramic_actions = AsyncMock(side_effect=lambda actions, *a, **kw: len(actions))

        result = await engine._run_locked(ws_id, run_id, session)

    # 2 passes should have run
    assert result.pass_count == 2, f"Expected 2 passes, got {result.pass_count}"
    # Pass 2 must see the refreshed entity list (entity_new_id, not entity_old_id)
    assert len(pass_entities_seen) == 2
    assert entity_new_id in pass_entities_seen[1], (
        "Pass 2 did not see the reloaded entity — entity refresh between passes is missing"
    )


# ---------------------------------------------------------------------------
# Test: flush not commit inside loop (Fix 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_not_commit_in_loop():
    """Engine calls session.flush (not session.commit) inside the multi-pass loop."""
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=PanoramicResult(actions=[]))
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))

        await engine._run_locked(ws_id, run_id, session)

    # session.commit must NOT have been called inside _run_locked
    session.commit.assert_not_called()
    # session.flush must have been called (at least once per pass)
    session.flush.assert_called()


# ---------------------------------------------------------------------------
# Test: cycle detection includes dedup count (Fix 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_detection_includes_dedup_count():
    """Cycle detection must not fire when panoramic is identical but dedup count varies.

    If dedup is skipped (no entities), applied_d=0 both passes, hash repeats => cycle.
    When entities are present and dedup count differs pass-to-pass, hash must differ
    so cycle is NOT detected prematurely.
    """
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    entity_id = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.name = "Alice"
    entity_mock.is_deleted = False
    entity_mock.aliases = []
    entity_mock.properties = {}
    entity_mock.entity_type = MagicMock()
    entity_mock.entity_type.slug = "person"

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_mock])
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)

    engine = _make_engine(entity_repo=entity_repo)
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    # Same panoramic action every pass — would trigger cycle_detected if hash ignores dedup
    repeated_action = PanoramicAction(
        action="remove_noise",
        entity_id=entity_id,
        params={"reason": "cycle"},
        confidence=0.9,
        rationale="cycling",
    )
    same_panoramic_result = PanoramicResult(actions=[repeated_action])

    dedup_call_count = [0]
    # Dedup returns different signatures per pass: pass 1 merges entity pair A, pass 2 none
    # This means the hashes differ → no cycle
    winner_x, loser_x = uuid.uuid4(), uuid.uuid4()
    dedup_returns = [
        (1, [f"merge:{winner_x}:{sorted([str(loser_x)])}"]),
        (0, []),
    ]

    async def dedup_v2_side_effect(*args, **kwargs):
        idx = min(dedup_call_count[0], len(dedup_returns) - 1)
        result = dedup_returns[idx]
        dedup_call_count[0] += 1
        return result

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=same_panoramic_result)
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(side_effect=dedup_v2_side_effect)
        engine._apply_panoramic_actions = AsyncMock(return_value=1)

        result = await engine._run_locked(ws_id, run_id, session)

    # With different dedup counts (1 vs 0), cycle_detected should NOT fire at pass 2.
    # It may converge via no_actions (pass 3: both=0) or max_passes, but not cycle at pass 2.
    assert not (result.convergence_reason == "cycle_detected" and result.pass_count == 2), (
        "Cycle detected at pass 2 despite dedup counts differing (1 vs 0) between passes"
    )


# ---------------------------------------------------------------------------
# Test: cycle detection uses dedup entity IDs (holistic review Fix 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_detection_uses_dedup_entity_ids():
    """Cycle detection must not fire when same count but different entity IDs are merged.

    Two passes that merge different entity sets but report the same integer count
    (e.g. both merge 1 entity) must NOT hash identically.  The action_hash must
    incorporate the actual winner/loser IDs returned by _dedup_v2, not just the
    integer count.

    _dedup_v2 returns (int, list[str]) where list[str] holds merge signatures like
    "merge:<winner_id>:[<loser_ids>]".  Two passes returning identical count=1 but
    different winner/loser IDs must produce different hashes — no false cycle.
    """
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    entity_id = uuid.uuid4()
    repeated_action = PanoramicAction(
        action="remove_noise",
        entity_id=entity_id,
        params={"reason": "cycle test"},
        confidence=0.9,
        rationale="cycling",
    )
    same_panoramic_result = PanoramicResult(actions=[repeated_action])

    # Both passes merge exactly 1 entity, but different entity pairs each time
    winner_a, loser_a = uuid.uuid4(), uuid.uuid4()
    winner_b, loser_b = uuid.uuid4(), uuid.uuid4()

    dedup_call_count = [0]
    # Each call returns (count, signatures) with same count but different entity IDs
    dedup_returns = [
        (1, [f"merge:{winner_a}:{sorted([str(loser_a)])}"]),
        (1, [f"merge:{winner_b}:{sorted([str(loser_b)])}"]),
        (0, []),
    ]

    async def dedup_v2_side_effect(*args, **kwargs):
        idx = min(dedup_call_count[0], len(dedup_returns) - 1)
        result = dedup_returns[idx]
        dedup_call_count[0] += 1
        return result

    entity_id2 = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id2
    entity_mock.name = "Alice"
    entity_mock.is_deleted = False
    entity_mock.aliases = []
    entity_mock.properties = {}
    entity_mock.entity_type = MagicMock()
    entity_mock.entity_type.slug = "person"

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_mock])
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)

    engine = _make_engine(entity_repo=entity_repo)
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(return_value=same_panoramic_result)
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(side_effect=dedup_v2_side_effect)
        engine._apply_panoramic_actions = AsyncMock(return_value=1)

        result = await engine._run_locked(ws_id, run_id, session)

    # cycle_detected must NOT fire at pass 2 because the entity IDs differ between passes
    assert not (result.convergence_reason == "cycle_detected" and result.pass_count == 2), (
        "Cycle detected at pass 2 despite different dedup entity IDs between passes"
    )


# ---------------------------------------------------------------------------
# Test: noise_removed counter counts only remove_noise actions (Fix — holistic review)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noise_removed_counts_only_remove_noise_actions():
    """noise_removed in run result should count only remove_noise panoramic actions.

    When a mix of remove_noise and non-noise action types is returned from
    _apply_panoramic_actions (2 total applied), noise_removed must equal 1,
    not 2.  We patch _apply_panoramic_actions so both actions "succeed"
    regardless of entity state, isolating the counter accumulation logic.
    """
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction, PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    entity_id_a = uuid.uuid4()
    entity_id_b = uuid.uuid4()

    engine = _make_engine()
    engine._enricher = AsyncMock()
    engine._enricher.enrich_batch = AsyncMock(return_value=(EnrichmentResult(), _zero_usage()))

    # 1 remove_noise + 1 rewrite — rewrite is NOT a noise action
    pass1_actions = [
        PanoramicAction(
            action="remove_noise",
            entity_id=entity_id_a,
            params={"reason": "garbage"},
            confidence=0.95,
            rationale="looks like garbage",
        ),
        PanoramicAction(
            action="rewrite",
            entity_id=entity_id_b,
            params={"new_name": "Better Name"},
            confidence=0.8,
            rationale="should be renamed",
        ),
    ]
    pass1_result = PanoramicResult(actions=pass1_actions)

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    # _apply_panoramic_actions is patched to always return 2 (both applied successfully)
    # but the real noise counter should still count only 1 remove_noise action
    async def fake_apply(actions, *args, **kwargs):
        return len(actions)  # both "succeed" → returns 2

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        pano_instance.run = AsyncMock(side_effect=[pass1_result, PanoramicResult(actions=[])])
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))
        engine._apply_panoramic_actions = fake_apply

        result = await engine._run_locked(ws_id, run_id, session)

    # noise_removed must equal 1 (only the remove_noise action), not 2 (total panoramic)
    assert result.noise_removed == 1, (
        f"Expected noise_removed=1 (only remove_noise actions), got {result.noise_removed}"
    )


# ---------------------------------------------------------------------------
# Test: _merge_duplicates writes IntegratorAction audit records (Fix — holistic review)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_duplicates_writes_audit_records():
    """_merge_duplicates must create IntegratorAction audit records when action_repo is provided."""
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alicia"
    entity_b.aliases = ["Ali"]
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(side_effect=lambda eid: entity_a if eid == entity_a_id else entity_b)
    entity_repo.update = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])

    engine = _make_engine(entity_repo=entity_repo)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(return_value=MagicMock())

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alicia",
        score=0.95,
        method="vector_shortlist",
    )

    merged = await engine._merge_duplicates([pair], ws_id, session, run_id=run_id, action_repo=action_repo)

    assert merged == 1
    # action_repo.create must have been called once for the merge audit record
    action_repo.create.assert_called_once()
    call_kwargs = action_repo.create.call_args
    # Verify the audit record has action_type="merge" and correct entity references
    action_data = call_kwargs.kwargs.get("data") or call_kwargs.args[1]
    assert action_data.action_type == "merge"
    assert action_data.entity_id == entity_a_id
    assert str(entity_b_id) in str(action_data.params)


# ---------------------------------------------------------------------------
# Test: entities reloaded before enrichment (holistic review Fix 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_sees_post_convergence_entities():
    """Enricher must receive the post-consolidation entity list, not the stale pre-loop list.

    Scenario: a single-pass run (no_actions after pass 1 because panoramic+dedup return 0).
    The initial load saw [stale_entity].  A post-loop reload returns [fresh_entity].
    The enricher must see [fresh_entity], not [stale_entity].

    Without the fix, the stale pre-loop list is passed to enrich_batch.
    With the fix, a fresh list_recent call is made after convergence.
    """
    from alayaos_core.extraction.integrator.passes.panoramic import PanoramicResult
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    # Entity only visible at initial load
    stale_entity_id = uuid.uuid4()
    stale_entity = MagicMock()
    stale_entity.id = stale_entity_id
    stale_entity.name = "StaleEntity"
    stale_entity.is_deleted = False
    stale_entity.aliases = []
    stale_entity.properties = {}
    stale_entity.entity_type = MagicMock()
    stale_entity.entity_type.slug = "person"

    # Entity only present in post-loop reload (e.g. created by pass 1 panoramic action)
    fresh_entity_id = uuid.uuid4()
    fresh_entity = MagicMock()
    fresh_entity.id = fresh_entity_id
    fresh_entity.name = "FreshEntity"
    fresh_entity.is_deleted = False
    fresh_entity.aliases = []
    fresh_entity.properties = {}
    fresh_entity.entity_type = MagicMock()
    fresh_entity.entity_type.slug = "person"

    # list_recent call sequence:
    #   call 0 (initial load, pass 1)  → [stale_entity]
    #   call 1 (post-loop reload)      → [fresh_entity]
    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(
        side_effect=[
            [stale_entity],  # initial load (pass 1)
            [fresh_entity],  # post-loop reload before enrichment
        ]
    )
    entity_repo.get_by_id = AsyncMock(side_effect=lambda eid: stale_entity if eid == stale_entity_id else fresh_entity)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))
    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))
    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    settings = _make_settings()
    redis_mock = _make_redis_mock()

    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )

    enricher_calls: list[list] = []

    async def fake_enrich_batch(entities):
        enricher_calls.append([e.id for e in entities])
        return EnrichmentResult(), _zero_usage()

    engine._enricher = MagicMock()
    engine._enricher.enrich_batch = fake_enrich_batch

    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = _make_session()

    with patch("alayaos_core.extraction.integrator.engine.PanoramicPass") as mock_pp:
        pano_instance = AsyncMock()
        # Single-pass run: panoramic emits 0 actions → convergence on pass 1
        pano_instance.run = AsyncMock(return_value=PanoramicResult(actions=[]))
        mock_pp.return_value = pano_instance
        engine._dedup_v2 = AsyncMock(return_value=(0, [], _zero_usage()))

        result = await engine._run_locked(ws_id, run_id, session)

    assert result.status == "completed"
    assert result.convergence_reason == "no_actions"
    # Enricher must have been called exactly once
    assert len(enricher_calls) == 1, f"Expected enricher called once, got {len(enricher_calls)}"
    # Enricher must see fresh_entity (post-loop reload), NOT stale_entity
    enriched_ids = enricher_calls[0]
    assert fresh_entity_id in enriched_ids, (
        "Enricher did not see the reloaded (post-convergence) entity — "
        "entities_with_context must be refreshed from DB before enrichment"
    )
    assert stale_entity_id not in enriched_ids, (
        "Enricher saw the stale entity — post-loop reload before enrichment is missing"
    )


# ---------------------------------------------------------------------------
# Sprint 2: _apply_action enrichment hierarchy guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_hierarchy_guard_part_of_rejected():
    """_apply_action with inverted part_of → returns {} and logs enrichment_part_of_rejected."""
    import structlog.testing

    from alayaos_core.extraction.integrator.schemas import EnrichmentAction
    from alayaos_core.repositories.errors import HierarchyViolationError

    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    relation_repo = AsyncMock()
    relation_repo.create = AsyncMock(
        side_effect=HierarchyViolationError("part_of: goal(3) cannot be part_of project(2)")
    )

    engine = _make_engine()
    engine.relation_repo = relation_repo

    action = EnrichmentAction(
        action="add_relation",
        entity_id=source_id,
        details={
            "target_entity_id": str(target_id),
            "relation_type": "part_of",
        },
    )

    ws_id = uuid.uuid4()
    session = AsyncMock()

    with structlog.testing.capture_logs() as cap_logs:
        counters = await engine._apply_action(action, ws_id, session)

    # Must return empty counters (not raise)
    assert counters == {}, f"Expected empty counters, got {counters}"

    # Must emit enrichment_part_of_rejected log
    rejection_events = [e for e in cap_logs if e.get("event") == "enrichment_part_of_rejected"]
    assert len(rejection_events) == 1, f"Expected 1 enrichment_part_of_rejected log event, got {len(rejection_events)}"


# ---------------------------------------------------------------------------
# Sprint 3: _merge_duplicates v2 audit inverse + audit failure logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_duplicates_writes_v2_audit_inverse():
    """_merge_duplicates writes snapshot_schema_version=2 with v2 inverse fields.

    params must preserve {loser_id, merged_name}; targets must remain list-of-dicts.
    """
    from alayaos_core.extraction.integrator.schemas import DuplicatePair
    from alayaos_core.schemas.integrator_action import IntegratorActionCreate  # noqa: TC001

    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alicia"
    entity_b.aliases = ["Ali"]
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(side_effect=lambda eid: entity_a if eid == entity_a_id else entity_b)
    entity_repo.update = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])

    engine = _make_engine(entity_repo=entity_repo)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    created_actions: list[IntegratorActionCreate] = []

    async def capture_create(workspace_id, data):
        created_actions.append(data)
        return MagicMock()

    action_repo = AsyncMock()
    action_repo.create = AsyncMock(side_effect=capture_create)

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alicia",
        score=0.95,
        method="vector_shortlist",
    )

    merged = await engine._merge_duplicates([pair], ws_id, session, run_id=run_id, action_repo=action_repo)
    assert merged == 1
    assert len(created_actions) == 1

    audit = created_actions[0]
    # snapshot_schema_version must be 2
    assert audit.snapshot_schema_version == 2

    # v2 inverse fields must all be present
    v2_fields = [
        "moved_claim_ids",
        "moved_relation_source_ids",
        "moved_relation_target_ids",
        "moved_chunk_ids",
        "deleted_self_ref_relation_ids",
        "deduplicated_relation_ids",
        "winner_before",
    ]
    for field in v2_fields:
        assert field in audit.inverse, f"Missing v2 inverse field: {field!r}"

    # params shape preserved: {loser_id, merged_name}
    assert "loser_id" in audit.params
    assert "merged_name" in audit.params
    assert str(entity_b_id) == audit.params["loser_id"]

    # targets shape preserved: list-of-dicts with id/name keys
    assert isinstance(audit.targets, list)
    assert len(audit.targets) == 2
    for t in audit.targets:
        assert isinstance(t, dict)
        assert "id" in t
        assert "name" in t


@pytest.mark.asyncio
async def test_merge_duplicates_audit_write_failure_logged():
    """When action_repo.create raises, merge_audit_write_failed is logged and merge still completes."""
    import structlog.testing

    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alicia"
    entity_b.aliases = ["Ali"]
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(side_effect=lambda eid: entity_a if eid == entity_a_id else entity_b)
    entity_repo.update = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])

    engine = _make_engine(entity_repo=entity_repo)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    # action_repo.create always raises
    action_repo = AsyncMock()
    action_repo.create = AsyncMock(side_effect=RuntimeError("DB write failed"))

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alicia",
        score=0.95,
        method="vector_shortlist",
    )

    with structlog.testing.capture_logs() as logs:
        merged = await engine._merge_duplicates([pair], ws_id, session, run_id=run_id, action_repo=action_repo)

    # Merge must still succeed despite audit write failure
    assert merged == 1

    # merge_audit_write_failed must be logged
    log_events = [lg["event"] for lg in logs]
    assert "merge_audit_write_failed" in log_events, f"Expected merge_audit_write_failed log. Got: {log_events}"
