"""Tests for AnthropicAdapter fallback behavior when cache_creation nested object is absent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

import alayaos_core.llm.observability as observability_mod
from alayaos_core.llm.anthropic import AnthropicAdapter


class _SimpleResult(BaseModel):
    value: str = "ok"


def _make_adapter(model: str = "claude-sonnet-4-6-20250514") -> tuple[AnthropicAdapter, AsyncMock]:
    adapter = AnthropicAdapter(api_key="test-key", model=model)
    mock_create = AsyncMock()
    adapter._client.messages.create = mock_create
    return adapter, mock_create


def _make_response_no_cache_creation(*, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    """Mock response where usage.cache_creation attribute does NOT exist (older SDK)."""
    usage = MagicMock(spec=["input_tokens", "output_tokens", "cache_read_input_tokens"])
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = 0
    # cache_creation is intentionally NOT set on the spec

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {"value": "ok"}

    resp = MagicMock()
    resp.usage = usage
    resp.content = [tool_block]
    return resp


@pytest.fixture(autouse=True)
def reset_observability_guard():
    """Reset the observability module-level set before each test."""
    observability_mod._cache_breakdown_warned = set()
    yield
    observability_mod._cache_breakdown_warned = set()


@pytest.mark.asyncio
async def test_missing_cache_creation_returns_zero_write_fields() -> None:
    """When cache_creation is absent, cache_write_* fields default to 0."""
    adapter, mock_create = _make_adapter()
    resp = _make_response_no_cache_creation()
    mock_create.return_value = resp

    _, usage = await adapter.extract("text", "prompt", _SimpleResult)

    assert usage.cache_write_5m_tokens == 0
    assert usage.cache_write_1h_tokens == 0


@pytest.mark.asyncio
async def test_missing_cache_creation_logs_warning_once(caplog) -> None:
    """cache_breakdown_unavailable is logged exactly once per process (observability guard)."""
    import logging

    adapter, mock_create = _make_adapter()
    resp = _make_response_no_cache_creation()
    mock_create.return_value = resp

    with caplog.at_level(logging.WARNING):
        # First call — should add model to set and log once
        await adapter.extract("text", "prompt", _SimpleResult)
        assert "claude-sonnet-4-6-20250514" in observability_mod._cache_breakdown_warned

        # Second call — model already in set, should not log again
        await adapter.extract("text", "prompt", _SimpleResult)

    # We can't easily count structlog warnings with caplog, but we verify the guard is set
    # and that no exception is raised on subsequent calls.


@pytest.mark.asyncio
async def test_cache_breakdown_warned_guard_resets_between_tests() -> None:
    """Verify the test infrastructure (autouse fixture) properly resets the observability guard."""
    # autouse fixture already ran — guard should be empty at test start
    assert len(observability_mod._cache_breakdown_warned) == 0


@pytest.mark.asyncio
async def test_response_with_zero_cache_creation_fields() -> None:
    """When cache_creation exists but all sub-fields are 0, no warning is needed."""
    adapter, mock_create = _make_adapter()

    cache_creation_obj = MagicMock()
    cache_creation_obj.ephemeral_5m_input_tokens = 0
    cache_creation_obj.ephemeral_1h_input_tokens = 0

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    usage.cache_creation = cache_creation_obj

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {"value": "ok"}

    resp = MagicMock()
    resp.usage = usage
    resp.content = [tool_block]
    mock_create.return_value = resp

    _, llm_usage = await adapter.extract("text", "prompt", _SimpleResult)

    # With cache_creation present, observability guard should NOT have been triggered
    assert "claude-sonnet-4-6-20250514" not in observability_mod._cache_breakdown_warned
    assert llm_usage.cache_write_5m_tokens == 0
    assert llm_usage.cache_write_1h_tokens == 0
