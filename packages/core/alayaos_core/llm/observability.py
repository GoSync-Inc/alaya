"""LLM observability: structured log events for call-level and run-level metrics.

Events emitted:
    llm.call_completed       — after every LLM API call, with latency and usage.
    llm.run_aggregated       — after recalc_usage at terminal extraction/integrator run.
    llm.cache_miss_below_threshold — when total_input < MODEL_CACHE_MINIMUM[model]
                                     (prompt too small to benefit from caching).
    llm.cache_breakdown_unavailable — once per process per model when the Anthropic
                                      cache_creation breakdown object is missing.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from alayaos_core.llm.pricing import MODEL_CACHE_MINIMUM

if TYPE_CHECKING:
    from alayaos_core.llm.interface import LLMUsage

log = structlog.get_logger("alayaos.llm")

# Module-level set: once a model is added here, llm.cache_breakdown_unavailable
# is NOT emitted again for that model in the same process lifetime.
# Tests reset this via: monkeypatch.setattr(observability, "_cache_breakdown_warned", set())
_cache_breakdown_warned: set[str] = set()


def log_call_completed(
    event: str,
    model: str,
    stage: str,
    latency_ms: int,
    usage: LLMUsage,
) -> None:
    """Emit llm.call_completed for a single LLM API call.

    Also emits llm.cache_miss_below_threshold when total_input < MODEL_CACHE_MINIMUM[model].
    The alarm is silenced for models not present in MODEL_CACHE_MINIMUM (e.g. "fake").

    Args:
        event: Event name (e.g. "llm.call_completed").
        model: LLM model identifier.
        stage: Pipeline stage (e.g. "cortex:classify", "crystallizer:extract").
        latency_ms: Wall-clock latency in milliseconds.
        usage: LLMUsage object from the adapter.
    """
    cache_hit_ratio = usage.tokens_cached / usage.total_input if usage.total_input > 0 else 0.0

    log.info(
        event,
        model=model,
        stage=stage,
        latency_ms=latency_ms,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        tokens_cached=usage.tokens_cached,
        cache_write_5m_tokens=usage.cache_write_5m_tokens,
        cache_write_1h_tokens=usage.cache_write_1h_tokens,
        total_input=usage.total_input,
        cache_hit_ratio=round(cache_hit_ratio, 4),
        cost_usd=usage.cost_usd,
    )

    # Below-threshold alarm: only for models with a known minimum.
    minimum = MODEL_CACHE_MINIMUM.get(model)
    if minimum is not None and usage.total_input < minimum:
        log.warning(
            "llm.cache_miss_below_threshold",
            model=model,
            stage=stage,
            total_input=usage.total_input,
            minimum=minimum,
        )


def log_run_aggregated(
    scope: str,
    run_id: uuid.UUID,
    workspace_id: uuid.UUID,
    tokens_in: int,
    tokens_out: int,
    tokens_cached: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    cost_usd: float,
    tokens_used: int,
    stage_breakdown: dict[str, Any] | None = None,
) -> None:
    """Emit llm.run_aggregated after recalc_usage at a terminal run transition.

    Args:
        scope: "extraction" or "integrator".
        run_id: UUID of the run.
        workspace_id: UUID of the workspace.
        tokens_in: Total non-cached input tokens.
        tokens_out: Total output tokens.
        tokens_cached: Total cache-read tokens.
        cache_write_5m_tokens: Total 5-min-TTL cache-write tokens.
        cache_write_1h_tokens: Total 1-hour-TTL cache-write tokens.
        cost_usd: Aggregated cost in USD.
        tokens_used: tokens_in + tokens_out (back-compat scalar).
        stage_breakdown: Optional per-stage dict with cache_hit_ratio etc.
    """
    total_input = tokens_in + tokens_cached + cache_write_5m_tokens + cache_write_1h_tokens
    cache_hit_ratio = tokens_cached / total_input if total_input > 0 else 0.0

    kwargs: dict[str, Any] = {
        "scope": scope,
        "run_id": str(run_id),
        "workspace_id": str(workspace_id),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "cache_write_5m_tokens": cache_write_5m_tokens,
        "cache_write_1h_tokens": cache_write_1h_tokens,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "total_input": total_input,
        "cache_hit_ratio": round(cache_hit_ratio, 4),
    }
    if stage_breakdown is not None:
        kwargs["stage_breakdown"] = stage_breakdown

    log.info("llm.run_aggregated", **kwargs)


def log_cache_breakdown_unavailable(model: str) -> None:
    """Emit llm.cache_breakdown_unavailable once per process per model.

    Subsequent calls for the same model are silently no-ops (the module-level
    _cache_breakdown_warned set acts as the once-per-process guard).

    Args:
        model: LLM model identifier for which cache_creation is missing.
    """
    if model in _cache_breakdown_warned:
        return
    _cache_breakdown_warned.add(model)
    log.warning(
        "llm.cache_breakdown_unavailable",
        model=model,
    )
