"""Tests for alayaos_core.llm.observability module.

Covers:
  - log_call_completed: event name, fields present.
  - 3-state cache miss alarm matrix:
      cold: total_input < minimum, no tokens_cached, no cache_write → alarm fires
        (because total_input < minimum).
      warm-write: cache writes occur, first run scenario → no alarm (total_input >= minimum).
      warm-read: cache reads occur, tokens_cached > 0 → no alarm (total_input >= minimum).
      The alarm fires when total_input < MODEL_CACHE_MINIMUM[model], regardless of cache state.
  - Fake adapter: "fake" is NOT in MODEL_CACHE_MINIMUM, so alarm is silenced naturally.
  - _cache_breakdown_warned once-per-process guard (keyed by model).
  - log_run_aggregated: event name and fields.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import alayaos_core.llm.observability as observability
from alayaos_core.llm.interface import LLMUsage
from alayaos_core.llm.pricing import MODEL_CACHE_MINIMUM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SONNET = "claude-sonnet-4-20250514"
_SONNET_MIN = MODEL_CACHE_MINIMUM[_SONNET]  # 2048


def _usage(
    tokens_in: int = 100,
    tokens_out: int = 50,
    tokens_cached: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    cost_usd: float = 0.001,
) -> LLMUsage:
    return LLMUsage(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cached=tokens_cached,
        cost_usd=cost_usd,
        cache_write_5m_tokens=cache_write_5m,
        cache_write_1h_tokens=cache_write_1h,
    )


@pytest.fixture(autouse=True)
def reset_cache_breakdown_warned(monkeypatch):
    """Reset the module-level set before each test to isolate once-per-process guard."""
    monkeypatch.setattr(observability, "_cache_breakdown_warned", set())


# ---------------------------------------------------------------------------
# log_call_completed — event shape
# ---------------------------------------------------------------------------


def test_log_call_completed_emits_correct_event_name():
    """log_call_completed emits the event passed as first argument."""
    with patch.object(observability.log, "info") as mock_info:
        usage = _usage()
        observability.log_call_completed("llm.call_completed", _SONNET, "cortex:classify", 120, usage)

    mock_info.assert_called_once()
    event_arg = mock_info.call_args[0][0]
    assert event_arg == "llm.call_completed"


def test_log_call_completed_includes_required_fields():
    """log_call_completed kwargs must include model, stage, latency_ms, usage fields."""
    with patch.object(observability.log, "info") as mock_info:
        usage = _usage(tokens_in=300, tokens_out=80, tokens_cached=50, cost_usd=0.002)
        observability.log_call_completed("llm.call_completed", _SONNET, "crystallizer:extract", 250, usage)

    kwargs = mock_info.call_args[1]
    assert kwargs["model"] == _SONNET
    assert kwargs["stage"] == "crystallizer:extract"
    assert kwargs["latency_ms"] == 250
    assert kwargs["tokens_in"] == 300
    assert kwargs["tokens_out"] == 80
    assert kwargs["tokens_cached"] == 50
    assert kwargs["cost_usd"] == pytest.approx(0.002)
    assert "cache_hit_ratio" in kwargs
    assert "total_input" in kwargs


def test_log_call_completed_cache_hit_ratio_computed_correctly():
    """cache_hit_ratio = tokens_cached / total_input."""
    # total_input = tokens_in + tokens_cached + cache_write_5m + cache_write_1h
    # = 1000 + 500 + 0 + 0 = 1500; ratio = 500/1500 ≈ 0.3333
    usage = _usage(tokens_in=1000, tokens_cached=500)
    with patch.object(observability.log, "info") as mock_info:
        observability.log_call_completed("llm.call_completed", _SONNET, "cortex", 100, usage)

    kwargs = mock_info.call_args[1]
    assert kwargs["cache_hit_ratio"] == pytest.approx(0.3333, abs=0.001)
    assert kwargs["total_input"] == 1500


def test_log_call_completed_zero_total_input_does_not_raise():
    """When total_input == 0, cache_hit_ratio should be 0 without ZeroDivisionError."""
    usage = _usage(tokens_in=0, tokens_out=0, tokens_cached=0)
    with patch.object(observability.log, "info"):
        # Must not raise
        observability.log_call_completed("llm.call_completed", _SONNET, "test", 0, usage)


# ---------------------------------------------------------------------------
# Cache miss alarm: 3-state matrix
# ---------------------------------------------------------------------------


def test_alarm_fires_when_total_input_below_minimum():
    """Alarm fires when total_input < MODEL_CACHE_MINIMUM[model] (cold / too small)."""
    # tokens_in=100 << sonnet minimum (2048) → alarm must fire
    usage = _usage(tokens_in=100, tokens_cached=0, cache_write_5m=0, cache_write_1h=0)
    with patch.object(observability.log, "info"), patch.object(observability.log, "warning") as mock_warn:
        observability.log_call_completed("llm.call_completed", _SONNET, "cortex", 50, usage)

    mock_warn.assert_called_once()
    event = mock_warn.call_args[0][0]
    assert event == "llm.cache_miss_below_threshold"
    kwargs = mock_warn.call_args[1]
    assert kwargs["model"] == _SONNET
    assert kwargs["total_input"] == 100
    assert kwargs["minimum"] == _SONNET_MIN


def test_no_alarm_when_total_input_at_or_above_minimum_warm_write():
    """Warm-write state: cache writes present, total_input >= minimum → no alarm."""
    # total_input = tokens_in(1500) + cache_write_5m(600) = 2100 >= 2048 → no alarm
    usage = _usage(tokens_in=1500, tokens_cached=0, cache_write_5m=600, cache_write_1h=0)
    assert usage.total_input >= _SONNET_MIN

    with patch.object(observability.log, "info"), patch.object(observability.log, "warning") as mock_warn:
        observability.log_call_completed("llm.call_completed", _SONNET, "cortex", 100, usage)

    mock_warn.assert_not_called()


def test_no_alarm_when_total_input_at_or_above_minimum_warm_read():
    """Warm-read state: tokens_cached > 0, total_input >= minimum → no alarm."""
    # total_input = tokens_in(1500) + tokens_cached(600) = 2100 >= 2048 → no alarm
    usage = _usage(tokens_in=1500, tokens_cached=600, cache_write_5m=0, cache_write_1h=0)
    assert usage.total_input >= _SONNET_MIN

    with patch.object(observability.log, "info"), patch.object(observability.log, "warning") as mock_warn:
        observability.log_call_completed("llm.call_completed", _SONNET, "crystallizer", 150, usage)

    mock_warn.assert_not_called()


def test_alarm_silenced_for_fake_model():
    """MODEL_CACHE_MINIMUM has no 'fake' key — alarm is naturally silenced for the fake adapter."""
    assert "fake" not in MODEL_CACHE_MINIMUM

    usage = _usage(tokens_in=10, tokens_cached=0)
    with patch.object(observability.log, "info"), patch.object(observability.log, "warning") as mock_warn:
        observability.log_call_completed("llm.call_completed", "fake", "cortex", 0, usage)

    mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# log_cache_breakdown_unavailable — once-per-process guard
# ---------------------------------------------------------------------------


def test_cache_breakdown_unavailable_emits_once_per_model():
    """First call for a model emits warning; second call is silently no-op."""
    with patch.object(observability.log, "warning") as mock_warn:
        observability.log_cache_breakdown_unavailable(_SONNET)
        observability.log_cache_breakdown_unavailable(_SONNET)  # second call — must be skipped

    assert mock_warn.call_count == 1
    event = mock_warn.call_args[0][0]
    assert event == "llm.cache_breakdown_unavailable"
    assert mock_warn.call_args[1]["model"] == _SONNET


def test_cache_breakdown_unavailable_different_models_both_emit():
    """Each distinct model emits once independently."""
    haiku = "claude-haiku-4-5-20251001"
    with patch.object(observability.log, "warning") as mock_warn:
        observability.log_cache_breakdown_unavailable(_SONNET)
        observability.log_cache_breakdown_unavailable(haiku)
        # Second calls — both should be no-ops
        observability.log_cache_breakdown_unavailable(_SONNET)
        observability.log_cache_breakdown_unavailable(haiku)

    assert mock_warn.call_count == 2
    models_warned = {c[1]["model"] for c in mock_warn.call_args_list}
    assert models_warned == {_SONNET, haiku}


def test_cache_breakdown_warned_set_keyed_by_model(monkeypatch):
    """The _cache_breakdown_warned set is correctly keyed by model string."""
    # Start with a clean set (guaranteed by autouse fixture)
    assert len(observability._cache_breakdown_warned) == 0

    with patch.object(observability.log, "warning"):
        observability.log_cache_breakdown_unavailable(_SONNET)

    assert _SONNET in observability._cache_breakdown_warned


# ---------------------------------------------------------------------------
# log_run_aggregated — event shape
# ---------------------------------------------------------------------------


def test_log_run_aggregated_emits_correct_event():
    """log_run_aggregated emits 'llm.run_aggregated' event."""
    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    with patch.object(observability.log, "info") as mock_info:
        observability.log_run_aggregated(
            scope="extraction",
            run_id=run_id,
            workspace_id=ws_id,
            tokens_in=1000,
            tokens_out=500,
            tokens_cached=300,
            cache_write_5m_tokens=100,
            cache_write_1h_tokens=50,
            cost_usd=0.01,
            tokens_used=1500,
        )

    mock_info.assert_called_once()
    assert mock_info.call_args[0][0] == "llm.run_aggregated"


def test_log_run_aggregated_includes_required_fields():
    """llm.run_aggregated kwargs must include all required fields."""
    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    with patch.object(observability.log, "info") as mock_info:
        observability.log_run_aggregated(
            scope="integrator",
            run_id=run_id,
            workspace_id=ws_id,
            tokens_in=2000,
            tokens_out=800,
            tokens_cached=600,
            cache_write_5m_tokens=200,
            cache_write_1h_tokens=100,
            cost_usd=0.05,
            tokens_used=2800,
        )

    kwargs = mock_info.call_args[1]
    assert kwargs["scope"] == "integrator"
    assert kwargs["run_id"] == str(run_id)
    assert kwargs["workspace_id"] == str(ws_id)
    assert kwargs["tokens_in"] == 2000
    assert kwargs["tokens_out"] == 800
    assert kwargs["tokens_cached"] == 600
    assert kwargs["cache_write_5m_tokens"] == 200
    assert kwargs["cache_write_1h_tokens"] == 100
    assert kwargs["cost_usd"] == pytest.approx(0.05)
    assert kwargs["tokens_used"] == 2800
    assert "cache_hit_ratio" in kwargs
    assert "total_input" in kwargs


def test_log_run_aggregated_stage_breakdown_optional():
    """stage_breakdown is included when provided, absent otherwise."""
    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    breakdown = {"cortex": {"cache_hit_ratio": 0.5}, "crystallizer": {"cache_hit_ratio": 0.8}}

    with patch.object(observability.log, "info") as mock_info:
        observability.log_run_aggregated(
            scope="extraction",
            run_id=run_id,
            workspace_id=ws_id,
            tokens_in=1000,
            tokens_out=400,
            tokens_cached=300,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            cost_usd=0.02,
            tokens_used=1400,
            stage_breakdown=breakdown,
        )

    kwargs = mock_info.call_args[1]
    assert kwargs["stage_breakdown"] == breakdown


def test_log_run_aggregated_no_stage_breakdown_by_default():
    """stage_breakdown not present in kwargs when not provided."""
    run_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    with patch.object(observability.log, "info") as mock_info:
        observability.log_run_aggregated(
            scope="extraction",
            run_id=run_id,
            workspace_id=ws_id,
            tokens_in=100,
            tokens_out=50,
            tokens_cached=0,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            cost_usd=0.001,
            tokens_used=150,
        )

    kwargs = mock_info.call_args[1]
    assert "stage_breakdown" not in kwargs
