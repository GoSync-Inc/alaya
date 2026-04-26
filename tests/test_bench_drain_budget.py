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

from scripts.bench import _drain_budget  # noqa: E402


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
