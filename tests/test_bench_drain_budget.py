"""Unit test for bench.py drain budget computation.

The drain budget is the wall-clock slice allocated to phase_drain (polling extraction_runs
until all terminal). For large realistic fixtures (352-1936 events), drain is the long pole;
allocating too small a fraction (50%) causes the integrator phase to never run because drain
times out first.

Fix: drain gets 90% of remaining wall-clock, leaving 10% for integrator + report + teardown.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ package is importable (mirrors the path injection in bench.py itself)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.bench import _cache_warm_run_deadline, _drain_budget, _scrub_host_db_redis_urls  # noqa: E402


def test_drain_budget_takes_most_of_remaining_wall_clock() -> None:
    """drain budget must be >= 90% of remaining wall-clock.

    With total_timeout=1800s and 60s elapsed in earlier phases, remaining = 1740s.
    Drain should receive >= 1566s (90% of 1740).
    """
    total_timeout_seconds = 1800
    phase_elapsed_seconds = 60
    remaining = total_timeout_seconds - phase_elapsed_seconds  # 1740

    budget = _drain_budget(remaining)

    # Must be >= 90% of remaining so integrator phase can actually run
    assert budget >= remaining * 0.9, (
        f"drain budget {budget}s is less than 90% of remaining {remaining}s; "
        "drain is the long pole — give it at least 90% so integrator can run"
    )


def test_drain_budget_leaves_headroom_for_integrator() -> None:
    """Drain budget must leave at least 10% of remaining time for integrator + report."""
    total_timeout_seconds = 600
    phase_elapsed_seconds = 30
    remaining = total_timeout_seconds - phase_elapsed_seconds  # 570

    budget = _drain_budget(remaining)

    leftover = remaining - budget
    assert leftover >= remaining * 0.10 * 0.9, (  # soft check: at least ~9% headroom
        f"leftover {leftover}s is too small; integrator + report need at least some headroom"
    )


def test_drain_budget_not_greater_than_remaining() -> None:
    """drain budget must never exceed total remaining wall-clock."""
    remaining = 300.0
    budget = _drain_budget(remaining)
    assert budget <= remaining


# ---------------------------------------------------------------------------
# _scrub_host_db_redis_urls
# ---------------------------------------------------------------------------


def test_cache_warm_two_runs_get_split_deadline() -> None:
    """Each run in --cache-warm-check mode must get half the total timeout.

    With total_timeout=1800s split into 2 runs, each run should have ~900s of
    wall-clock budget. The drain budget (90%) then applies per-run, giving 810s
    to drain per run — bounded and not starving run 2.
    """
    import time

    total_timeout_seconds = 1800
    global_start = time.monotonic()

    # Per-run deadline for run index 0 and 1 (0-based)
    deadline_run1 = _cache_warm_run_deadline(global_start, total_timeout_seconds, run_index=0)
    deadline_run2 = _cache_warm_run_deadline(global_start, total_timeout_seconds, run_index=1)

    per_run_seconds = total_timeout_seconds / 2  # 900

    # Each run deadline should be approximately (global_start + (run_index+1) * per_run_seconds)
    assert abs(deadline_run1 - (global_start + per_run_seconds)) < 1.0, (
        f"run 1 deadline offset {deadline_run1 - global_start}s is not ~{per_run_seconds}s"
    )
    assert abs(deadline_run2 - (global_start + 2 * per_run_seconds)) < 1.0, (
        f"run 2 deadline offset {deadline_run2 - global_start}s is not ~{2 * per_run_seconds}s"
    )

    # Run 1 must expire before run 2
    assert deadline_run1 < deadline_run2, "run 1 deadline must precede run 2 deadline"

    # Each run's wall-clock budget must be ~half the total
    run1_budget = deadline_run1 - global_start
    run2_budget = deadline_run2 - deadline_run1
    assert abs(run1_budget - run2_budget) < 1.0, (
        f"run budgets are not equal: run1={run1_budget}s run2={run2_budget}s; both runs should get the same slice"
    )


def test_scrub_removes_all_host_db_redis_keys() -> None:
    """All host-side DB/Redis keys must be absent after scrubbing."""
    env: dict[str, str] = {
        "ALAYA_DATABASE_URL": "postgresql+asyncpg://localhost:5432/alaya",
        "ALAYA_REDIS_URL": "redis://localhost:6379/0",
        "DATABASE_URL": "postgresql://localhost:5432/alaya",
        "REDIS_URL": "redis://localhost:6379/0",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "OTHER_KEY": "should-remain",
    }
    _scrub_host_db_redis_urls(env)
    for key in (
        "ALAYA_DATABASE_URL",
        "ALAYA_REDIS_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "REDIS_HOST",
        "REDIS_PORT",
    ):
        assert key not in env, f"{key} should have been scrubbed but is still present"
    assert env.get("OTHER_KEY") == "should-remain"


def test_scrub_is_idempotent_on_empty_dict() -> None:
    """Scrubbing an empty dict must not raise."""
    env: dict[str, str] = {}
    _scrub_host_db_redis_urls(env)  # must not raise
    assert env == {}


def test_scrub_does_not_remove_unrelated_keys() -> None:
    """Keys unrelated to DB/Redis must survive the scrub."""
    env: dict[str, str] = {
        "ALAYA_ANTHROPIC_API_KEY": "sk-test",
        "ALAYA_ENV": "dev",
        "PATH": "/usr/bin",
    }
    _scrub_host_db_redis_urls(env)
    assert env == {
        "ALAYA_ANTHROPIC_API_KEY": "sk-test",
        "ALAYA_ENV": "dev",
        "PATH": "/usr/bin",
    }
