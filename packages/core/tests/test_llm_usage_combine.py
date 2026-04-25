"""Tests for LLMUsage.zero() and LLMUsage.combine() factory methods.

Covers:
- LLMUsage.zero() returns all-zero fields
- LLMUsage.combine() sums all 6 fields (tokens_in, tokens_out, tokens_cached,
  cache_write_5m_tokens, cache_write_1h_tokens, cost_usd)
- cache_write_5m_tokens and cache_write_1h_tokens propagate correctly (regression
  for the _combine_usage() bug that silently dropped these fields)
- Combining zero usages is identity
- Combining three usages works (varargs)
"""

from __future__ import annotations

import pytest

from alayaos_core.llm.interface import LLMUsage

# ---------------------------------------------------------------------------
# LLMUsage.zero()
# ---------------------------------------------------------------------------


def test_zero_returns_all_zero_fields():
    z = LLMUsage.zero()
    assert z.tokens_in == 0
    assert z.tokens_out == 0
    assert z.tokens_cached == 0
    assert z.cache_write_5m_tokens == 0
    assert z.cache_write_1h_tokens == 0
    assert z.cost_usd == 0.0


def test_zero_total_input_is_zero():
    assert LLMUsage.zero().total_input == 0


def test_zero_cache_hit_ratio_is_zero():
    assert LLMUsage.zero().cache_hit_ratio == 0.0


# ---------------------------------------------------------------------------
# LLMUsage.combine() — field propagation
# ---------------------------------------------------------------------------


def _make_usage(
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_cached: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    cost_usd: float = 0.0,
) -> LLMUsage:
    return LLMUsage(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cached=tokens_cached,
        cache_write_5m_tokens=cache_write_5m_tokens,
        cache_write_1h_tokens=cache_write_1h_tokens,
        cost_usd=cost_usd,
    )


def test_combine_sums_tokens_in():
    u1 = _make_usage(tokens_in=100)
    u2 = _make_usage(tokens_in=200)
    assert LLMUsage.combine(u1, u2).tokens_in == 300


def test_combine_sums_tokens_out():
    u1 = _make_usage(tokens_out=50)
    u2 = _make_usage(tokens_out=75)
    assert LLMUsage.combine(u1, u2).tokens_out == 125


def test_combine_sums_tokens_cached():
    u1 = _make_usage(tokens_cached=400)
    u2 = _make_usage(tokens_cached=600)
    assert LLMUsage.combine(u1, u2).tokens_cached == 1000


def test_combine_propagates_cache_write_5m_tokens():
    """Regression: old _combine_usage() silently dropped cache_write_5m_tokens."""
    u1 = _make_usage(cache_write_5m_tokens=300)
    u2 = _make_usage(cache_write_5m_tokens=150)
    result = LLMUsage.combine(u1, u2)
    assert result.cache_write_5m_tokens == 450


def test_combine_propagates_cache_write_1h_tokens():
    """Regression: old _combine_usage() silently dropped cache_write_1h_tokens."""
    u1 = _make_usage(cache_write_1h_tokens=200)
    u2 = _make_usage(cache_write_1h_tokens=800)
    result = LLMUsage.combine(u1, u2)
    assert result.cache_write_1h_tokens == 1000


def test_combine_sums_cost_usd():
    u1 = _make_usage(cost_usd=0.01)
    u2 = _make_usage(cost_usd=0.02)
    assert LLMUsage.combine(u1, u2).cost_usd == pytest.approx(0.03)


def test_combine_all_fields_together():
    """All 6 fields summed correctly in one combined call."""
    u1 = _make_usage(
        tokens_in=100,
        tokens_out=50,
        tokens_cached=400,
        cache_write_5m_tokens=300,
        cache_write_1h_tokens=200,
        cost_usd=0.01,
    )
    u2 = _make_usage(
        tokens_in=200,
        tokens_out=75,
        tokens_cached=600,
        cache_write_5m_tokens=150,
        cache_write_1h_tokens=800,
        cost_usd=0.02,
    )
    result = LLMUsage.combine(u1, u2)
    assert result.tokens_in == 300
    assert result.tokens_out == 125
    assert result.tokens_cached == 1000
    assert result.cache_write_5m_tokens == 450
    assert result.cache_write_1h_tokens == 1000
    assert result.cost_usd == pytest.approx(0.03)


def test_combine_with_zero_is_identity():
    u = _make_usage(
        tokens_in=10,
        tokens_out=5,
        tokens_cached=20,
        cache_write_5m_tokens=30,
        cache_write_1h_tokens=40,
        cost_usd=0.005,
    )
    result = LLMUsage.combine(u, LLMUsage.zero())
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.tokens_cached == 20
    assert result.cache_write_5m_tokens == 30
    assert result.cache_write_1h_tokens == 40
    assert result.cost_usd == pytest.approx(0.005)


def test_combine_three_usages():
    """combine() accepts variable number of arguments (varargs)."""
    u1 = _make_usage(tokens_in=100, cache_write_5m_tokens=10)
    u2 = _make_usage(tokens_in=200, cache_write_5m_tokens=20)
    u3 = _make_usage(tokens_in=300, cache_write_5m_tokens=30)
    result = LLMUsage.combine(u1, u2, u3)
    assert result.tokens_in == 600
    assert result.cache_write_5m_tokens == 60


def test_combine_single_usage_returns_equivalent():
    """combine() with a single argument returns an equivalent usage."""
    u = _make_usage(tokens_in=42, cache_write_1h_tokens=99)
    result = LLMUsage.combine(u)
    assert result.tokens_in == 42
    assert result.cache_write_1h_tokens == 99


# ---------------------------------------------------------------------------
# Cortex classifier flow regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cortex_classifier_combine_propagates_cache_write_fields():
    """Regression: classify_and_verify() combined usage must include cache_write fields.

    Simulates a two-LLM-call flow (classify + verify) where both calls return
    cache_write_5m_tokens=N. The combined usage returned by classify_and_verify
    must sum them — previously _combine_usage() silently dropped these fields.
    """
    from unittest.mock import AsyncMock

    from alayaos_core.extraction.cortex.chunker import RawChunk
    from alayaos_core.extraction.cortex.classifier import CortexClassifier
    from alayaos_core.extraction.cortex.schemas import DomainScores

    # Build a minimal DomainScores with all required fields
    fake_scores = DomainScores(
        project=0.9,
        decision=0.1,
        strategic=0.0,
        risk=0.0,
        people=0.0,
        engineering=0.0,
        knowledge=0.0,
        customer=0.0,
        smalltalk=0.0,
    )
    classify_usage = LLMUsage(
        tokens_in=100,
        tokens_out=20,
        tokens_cached=400,
        cache_write_5m_tokens=50,
        cache_write_1h_tokens=10,
        cost_usd=0.001,
    )
    verify_usage = LLMUsage(
        tokens_in=110,
        tokens_out=22,
        tokens_cached=410,
        cache_write_5m_tokens=55,
        cache_write_1h_tokens=12,
        cost_usd=0.0012,
    )

    mock_llm = AsyncMock()
    mock_llm.extract = AsyncMock(
        side_effect=[
            (fake_scores, classify_usage),
            (fake_scores, verify_usage),
        ]
    )

    chunk = RawChunk(
        text="Project Alpha hit its milestone last week.",
        index=0,
        total=1,
        source_type="event",
        source_id="00000000-0000-0000-0000-000000000001",
        token_count=8,
    )
    classifier = CortexClassifier(llm=mock_llm)
    _scores, _changed, combined = await classifier.classify_and_verify(chunk)

    # Both cache_write fields must be summed
    assert combined.cache_write_5m_tokens == 105  # 50 + 55
    assert combined.cache_write_1h_tokens == 22  # 10 + 12
    assert combined.tokens_in == 210
    assert combined.tokens_cached == 810
