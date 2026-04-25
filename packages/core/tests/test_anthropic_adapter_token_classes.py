"""Tests for AnthropicAdapter token-class population and cost math.

Covers:
- Token hash equality (charter SC3)
- 3-state cache matrix: cold / warm-write / warm-read
- Correct cost arithmetic using pricing.py (no buggy subtraction)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from alayaos_core.llm.anthropic import AnthropicAdapter
from alayaos_core.llm.interface import LLMUsage
from alayaos_core.llm.pricing import PRICING


class _SimpleResult(BaseModel):
    value: str = "ok"


def _make_response(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    ephemeral_5m_input_tokens: int = 0,
    ephemeral_1h_input_tokens: int = 0,
) -> MagicMock:
    """Build a mock Anthropic response with nested usage fields."""
    cache_creation_obj = MagicMock()
    cache_creation_obj.ephemeral_5m_input_tokens = ephemeral_5m_input_tokens
    cache_creation_obj.ephemeral_1h_input_tokens = ephemeral_1h_input_tokens

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read_input_tokens
    usage.cache_creation_input_tokens = cache_creation_input_tokens
    usage.cache_creation = cache_creation_obj

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.input = {"value": "ok"}

    resp = MagicMock()
    resp.usage = usage
    resp.content = [tool_use_block]
    return resp


def _make_adapter(model: str = "claude-sonnet-4-6-20250514") -> tuple[AnthropicAdapter, AsyncMock]:
    adapter = AnthropicAdapter(api_key="test-key", model=model)
    mock_create = AsyncMock()
    adapter._client.messages.create = mock_create
    return adapter, mock_create


@pytest.mark.asyncio
async def test_cold_cache_state_token_hash_equality() -> None:
    """Cold cache: no cache reads or writes. Token hash equality holds."""
    adapter, mock_create = _make_adapter()
    resp = _make_response(input_tokens=1000, output_tokens=200)
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    # Charter SC3 hash equality
    assert (
        usage.tokens_in
        + usage.tokens_out
        + usage.tokens_cached
        + usage.cache_write_5m_tokens
        + usage.cache_write_1h_tokens
    ) == (
        resp.usage.input_tokens
        + resp.usage.output_tokens
        + resp.usage.cache_read_input_tokens
        + resp.usage.cache_creation_input_tokens
    )

    assert usage.tokens_in == 1000
    assert usage.tokens_out == 200
    assert usage.tokens_cached == 0
    assert usage.cache_write_5m_tokens == 0
    assert usage.cache_write_1h_tokens == 0


@pytest.mark.asyncio
async def test_warm_write_cache_state() -> None:
    """Warm-write: prompt written to 5m cache. Correct fields populated."""
    adapter, mock_create = _make_adapter()
    resp = _make_response(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=500,
        ephemeral_5m_input_tokens=500,
        ephemeral_1h_input_tokens=0,
    )
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    assert usage.tokens_in == 100
    assert usage.tokens_out == 50
    assert usage.tokens_cached == 0
    assert usage.cache_write_5m_tokens == 500
    assert usage.cache_write_1h_tokens == 0

    # Hash equality
    assert (
        usage.tokens_in
        + usage.tokens_out
        + usage.tokens_cached
        + usage.cache_write_5m_tokens
        + usage.cache_write_1h_tokens
    ) == (
        resp.usage.input_tokens
        + resp.usage.output_tokens
        + resp.usage.cache_read_input_tokens
        + resp.usage.cache_creation_input_tokens
    )


@pytest.mark.asyncio
async def test_warm_read_cache_state() -> None:
    """Warm-read: prompt served from cache. cache_read_input_tokens populated."""
    adapter, mock_create = _make_adapter()
    resp = _make_response(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=800,
        cache_creation_input_tokens=0,
    )
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    assert usage.tokens_cached == 800
    assert usage.cache_write_5m_tokens == 0
    assert usage.cache_write_1h_tokens == 0

    # Hash equality
    assert (
        usage.tokens_in
        + usage.tokens_out
        + usage.tokens_cached
        + usage.cache_write_5m_tokens
        + usage.cache_write_1h_tokens
    ) == (
        resp.usage.input_tokens
        + resp.usage.output_tokens
        + resp.usage.cache_read_input_tokens
        + resp.usage.cache_creation_input_tokens
    )


@pytest.mark.asyncio
async def test_correct_cost_cold_no_buggy_subtraction() -> None:
    """Cold cache cost: must use pricing.py, no subtraction of cache_read from input."""
    model = "claude-sonnet-4-6-20250514"
    adapter, mock_create = _make_adapter(model)
    resp = _make_response(input_tokens=1000, output_tokens=200)
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    price = PRICING[model]
    expected_cost = price.cost_usd(usage)
    assert usage.cost_usd == pytest.approx(expected_cost, rel=1e-9)

    # Verify no double-subtraction bug: old code would subtract cached from input.
    # With no caching, input cost should be exactly tokens_in * input_per_mtok / 1M.
    assert usage.cost_usd == pytest.approx(1000 * 3.0 / 1_000_000 + 200 * 15.0 / 1_000_000)


@pytest.mark.asyncio
async def test_correct_cost_warm_write() -> None:
    """Warm-write cost: cache_write_5m billed at 1.25x input rate."""
    model = "claude-sonnet-4-6-20250514"
    adapter, mock_create = _make_adapter(model)
    resp = _make_response(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=500,
        ephemeral_5m_input_tokens=500,
    )
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    price = PRICING[model]
    expected = price.cost_usd(usage)
    assert usage.cost_usd == pytest.approx(expected, rel=1e-9)


@pytest.mark.asyncio
async def test_correct_cost_warm_read() -> None:
    """Warm-read cost: cache_read billed at 0.10x input rate."""
    model = "claude-sonnet-4-6-20250514"
    adapter, mock_create = _make_adapter(model)
    resp = _make_response(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=800,
    )
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    price = PRICING[model]
    expected = price.cost_usd(usage)
    assert usage.cost_usd == pytest.approx(expected, rel=1e-9)


@pytest.mark.asyncio
async def test_stage_kwarg_accepted() -> None:
    """extract() must accept a stage= kwarg without error."""
    adapter, mock_create = _make_adapter()
    resp = _make_response(input_tokens=10, output_tokens=5)
    mock_create.return_value = resp

    _result, usage = await adapter.extract("text", "prompt", _SimpleResult, stage="cortex")
    assert isinstance(usage, LLMUsage)
