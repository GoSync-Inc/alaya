"""Tests for FallbackLLMAdapter stage forwarding.

Task 6 (Sprint 3): FallbackLLMAdapter.extract(stage="cortex") must forward stage
to the inner adapter (not raise, not swallow the kwarg).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from alayaos_core.llm.fallback import FallbackLLMAdapter
from alayaos_core.llm.interface import LLMUsage


class SimpleModel(BaseModel):
    name: str = "ok"


_USAGE = LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.0)


@pytest.mark.asyncio
async def test_fallback_adapter_forwards_stage_to_inner_adapter():
    """FallbackLLMAdapter.extract(stage=...) must forward stage to the inner adapter."""
    primary = MagicMock()
    primary.extract = AsyncMock(return_value=(SimpleModel(name="primary"), _USAGE))

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[])
    result, _usage = await adapter.extract("text", "sys", SimpleModel, stage="cortex")

    # The inner adapter must have been called with stage="cortex"
    primary.extract.assert_awaited_once()
    _args, kwargs = primary.extract.call_args
    assert kwargs.get("stage") == "cortex"
    assert result.name == "primary"


@pytest.mark.asyncio
async def test_fallback_adapter_stage_forwarded_to_fallback_on_primary_failure():
    """When primary fails, stage is forwarded to the fallback adapter too."""
    primary = MagicMock()
    primary.extract = AsyncMock(side_effect=RuntimeError("primary down"))

    fallback = MagicMock()
    fallback.extract = AsyncMock(return_value=(SimpleModel(name="fallback"), _USAGE))

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[fallback])
    result, _usage = await adapter.extract("text", "sys", SimpleModel, stage="crystallizer:extract")

    fallback.extract.assert_awaited_once()
    _args, kwargs = fallback.extract.call_args
    assert kwargs.get("stage") == "crystallizer:extract"
    assert result.name == "fallback"


@pytest.mark.asyncio
async def test_fallback_adapter_does_not_raise_with_stage_kwarg():
    """FallbackLLMAdapter.extract(stage='cortex') does not raise."""
    primary = MagicMock()
    primary.extract = AsyncMock(return_value=(SimpleModel(), _USAGE))

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[])
    # Must not raise
    result, _ = await adapter.extract("text", "sys", SimpleModel, stage="cortex")
    assert result is not None
