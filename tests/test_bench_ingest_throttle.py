"""Tests for ingest throttling in scripts/bench_ingest.py and bench.py phase_ingest.

Verifies that:
  - ingest_fixture accepts an `rps` parameter
  - when rps is set, time.sleep is called between each request
  - the sleep duration equals 1/rps
  - rps=None (default) skips throttling entirely
  - phase_ingest auto-selects rps based on fixture event count
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_REPO_ROOT = Path(__file__).parent.parent
import sys

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.bench_ingest import ingest_fixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fixture(tmp_path: Path, n: int = 3) -> Path:
    """Write a minimal JSONL fixture with n events."""
    lines = [json.dumps({"id": f"evt{i:04d}", "raw_text": f"Event text {i}"}) for i in range(n)]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(lines))
    return p


def _mock_ok_response(event_id: str = "aaaa-0001", run_id: str = "bbbb-0001") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "data": {
            "event_id": event_id,
            "extraction_run_id": run_id,
            "status": "pending",
        }
    }
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_fixture_rps_calls_sleep_between_events(tmp_path: Path) -> None:
    """When rps=2, time.sleep(0.5) is called once between each pair of events."""
    fixture = _make_fixture(tmp_path, n=3)

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_ok_response()

    with (
        patch("scripts.bench_ingest.httpx.Client", return_value=mock_client),
        patch("scripts.bench_ingest.time.sleep") as mock_sleep,
    ):
        results = ingest_fixture(api_url="http://localhost/api/v1", key="ak_test", fixture_path=fixture, rps=2)

    # 3 events → 2 sleeps (after event 0, after event 1; not after the last)
    assert mock_sleep.call_count == 2
    for c in mock_sleep.call_args_list:
        assert abs(c.args[0] - 0.5) < 1e-9
    assert len(results) == 3
    assert all("run_id" in r for r in results)


def test_ingest_fixture_no_rps_skips_sleep(tmp_path: Path) -> None:
    """When rps is not provided (None), time.sleep is never called."""
    fixture = _make_fixture(tmp_path, n=3)

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_ok_response()

    with (
        patch("scripts.bench_ingest.httpx.Client", return_value=mock_client),
        patch("scripts.bench_ingest.time.sleep") as mock_sleep,
    ):
        results = ingest_fixture(api_url="http://localhost/api/v1", key="ak_test", fixture_path=fixture)

    mock_sleep.assert_not_called()
    assert len(results) == 3


def test_ingest_fixture_rps_not_called_after_last_event(tmp_path: Path) -> None:
    """Sleep is NOT called after the final event (only between events)."""
    fixture = _make_fixture(tmp_path, n=1)

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_ok_response()

    with (
        patch("scripts.bench_ingest.httpx.Client", return_value=mock_client),
        patch("scripts.bench_ingest.time.sleep") as mock_sleep,
    ):
        ingest_fixture(api_url="http://localhost/api/v1", key="ak_test", fixture_path=fixture, rps=5)

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# phase_ingest auto-rps tests
# ---------------------------------------------------------------------------


def test_ingest_rps_large_fixture_returns_throttle_rps(tmp_path: Path) -> None:
    """_ingest_rps returns INGEST_THROTTLE_RPS when event_count > INGEST_THROTTLE_THRESHOLD."""
    from scripts.bench import INGEST_THROTTLE_THRESHOLD, INGEST_THROTTLE_RPS, _ingest_rps

    assert _ingest_rps(INGEST_THROTTLE_THRESHOLD + 1) == INGEST_THROTTLE_RPS
    assert _ingest_rps(1000) == INGEST_THROTTLE_RPS


def test_ingest_rps_small_fixture_returns_none(tmp_path: Path) -> None:
    """_ingest_rps returns None when event_count <= INGEST_THROTTLE_THRESHOLD."""
    from scripts.bench import INGEST_THROTTLE_THRESHOLD, _ingest_rps

    assert _ingest_rps(INGEST_THROTTLE_THRESHOLD) is None
    assert _ingest_rps(1) is None
    assert _ingest_rps(0) is None
