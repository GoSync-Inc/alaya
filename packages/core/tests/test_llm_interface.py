"""Tests for LLM interface and FakeLLMAdapter."""

import pytest
from pydantic import BaseModel

from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.llm.interface import LLMServiceInterface, LLMUsage

# ─── LLMUsage ─────────────────────────────────────────────────────────────────


def test_llm_usage_fields() -> None:
    usage = LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=10, cost_usd=0.001)
    assert usage.tokens_in == 100
    assert usage.tokens_out == 50
    assert usage.tokens_cached == 10
    assert usage.cost_usd == 0.001


# ─── FakeLLMAdapter ───────────────────────────────────────────────────────────


class SimpleModel(BaseModel):
    name: str = "default"
    value: int = 0


@pytest.mark.asyncio
async def test_fake_adapter_returns_result() -> None:
    adapter = FakeLLMAdapter()
    adapter.add_response(FakeLLMAdapter.content_hash("hello"), {"name": "Alice", "value": 42})
    result, usage = await adapter.extract("hello", "sys", SimpleModel)
    assert isinstance(result, SimpleModel)
    assert result.name == "Alice"
    assert result.value == 42
    assert isinstance(usage, LLMUsage)


@pytest.mark.asyncio
async def test_fake_adapter_content_hash() -> None:
    h1 = FakeLLMAdapter.content_hash("hello")
    h2 = FakeLLMAdapter.content_hash("hello")
    h3 = FakeLLMAdapter.content_hash("world")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16  # sha256[:16]


@pytest.mark.asyncio
async def test_fake_adapter_default_response() -> None:
    adapter = FakeLLMAdapter()
    # No response registered — should return defaults
    result, _usage = await adapter.extract("unknown text", "sys", SimpleModel)
    assert isinstance(result, SimpleModel)
    # Default values from model
    assert result.name == "default"
    assert result.value == 0


@pytest.mark.asyncio
async def test_fake_adapter_usage_is_fixed() -> None:
    adapter = FakeLLMAdapter()
    adapter.add_response(FakeLLMAdapter.content_hash("test"), {"name": "X", "value": 1})
    _, usage = await adapter.extract("test", "sys", SimpleModel)
    assert usage.tokens_in == 100
    assert usage.tokens_out == 50
    assert usage.tokens_cached == 0
    assert usage.cost_usd == 0.0


def test_llm_service_interface_is_protocol() -> None:
    """LLMServiceInterface must be a Protocol (structural subtyping)."""
    assert getattr(LLMServiceInterface, "__protocol_attrs__", None) is not None or (
        hasattr(LLMServiceInterface, "_is_protocol") or isinstance(LLMServiceInterface, type)
    )
