"""Tests for FallbackLLMAdapter and create_llm_service factory."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, SecretStr

from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.llm.interface import LLMUsage


class SimpleModel(BaseModel):
    name: str = "default"
    value: int = 0


_USAGE = LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.0)


def _make_mock_adapter(result: SimpleModel | None = None, raises: Exception | None = None):
    """Return a mock LLM adapter."""
    adapter = MagicMock()
    if raises is not None:
        adapter.extract = AsyncMock(side_effect=raises)
    else:
        adapter.extract = AsyncMock(return_value=(result or SimpleModel(name="mock", value=1), _USAGE))
    return adapter


# ─── FallbackLLMAdapter ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_primary_succeeds_no_fallback_called() -> None:
    """When primary succeeds, fallback.extract is never called."""
    from alayaos_core.llm.fallback import FallbackLLMAdapter

    primary = _make_mock_adapter(result=SimpleModel(name="primary", value=10))
    fallback = _make_mock_adapter(result=SimpleModel(name="fallback", value=99))

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[fallback])
    result, _usage = await adapter.extract("text", "sys", SimpleModel)

    assert result.name == "primary"
    assert result.value == 10
    primary.extract.assert_awaited_once()
    fallback.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_primary_fails_fallback_called() -> None:
    """When primary raises, fallback is used and its result is returned."""
    from alayaos_core.llm.fallback import FallbackLLMAdapter

    primary = _make_mock_adapter(raises=RuntimeError("primary down"))
    fallback = _make_mock_adapter(result=SimpleModel(name="fallback", value=99))

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[fallback])
    result, _usage = await adapter.extract("text", "sys", SimpleModel)

    assert result.name == "fallback"
    assert result.value == 99
    primary.extract.assert_awaited_once()
    fallback.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_fail_raises_last_error() -> None:
    """When all providers fail, the last exception is raised."""
    from alayaos_core.llm.fallback import FallbackLLMAdapter

    err1 = RuntimeError("primary down")
    err2 = RuntimeError("fallback down")

    primary = _make_mock_adapter(raises=err1)
    fallback = _make_mock_adapter(raises=err2)

    adapter = FallbackLLMAdapter(primary=primary, fallbacks=[fallback])
    with pytest.raises(RuntimeError, match="fallback down"):
        await adapter.extract("text", "sys", SimpleModel)


# ─── create_llm_service factory ──────────────────────────────────────────────


def _make_settings(**kwargs):
    """Build a minimal Settings-like object via MagicMock."""
    from alayaos_core.config import Settings

    defaults = {
        "EXTRACTION_LLM_PROVIDER": "fake",
        "LLM_FALLBACK_PROVIDERS": [],
        "ANTHROPIC_API_KEY": SecretStr("test-key"),
        "ANTHROPIC_MODEL": "claude-sonnet-4-20250514",
    }
    defaults.update(kwargs)
    s = MagicMock(spec=Settings)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def test_factory_creates_fake() -> None:
    """Factory returns FakeLLMAdapter when provider='fake'."""
    from alayaos_core.llm.factory import create_llm_service

    settings = _make_settings(EXTRACTION_LLM_PROVIDER="fake", LLM_FALLBACK_PROVIDERS=[])
    service = create_llm_service(settings)
    assert isinstance(service, FakeLLMAdapter)


def test_factory_creates_anthropic() -> None:
    """Factory returns AnthropicAdapter when provider='anthropic'."""
    from alayaos_core.llm.anthropic import AnthropicAdapter
    from alayaos_core.llm.factory import create_llm_service

    settings = _make_settings(EXTRACTION_LLM_PROVIDER="anthropic", LLM_FALLBACK_PROVIDERS=[])
    service = create_llm_service(settings)
    assert isinstance(service, AnthropicAdapter)


def test_factory_with_fallback() -> None:
    """Factory returns FallbackLLMAdapter when LLM_FALLBACK_PROVIDERS is non-empty."""
    from alayaos_core.llm.factory import create_llm_service
    from alayaos_core.llm.fallback import FallbackLLMAdapter

    settings = _make_settings(
        EXTRACTION_LLM_PROVIDER="fake",
        LLM_FALLBACK_PROVIDERS=["fake"],
    )
    service = create_llm_service(settings)
    assert isinstance(service, FallbackLLMAdapter)


def test_factory_unknown_provider_raises() -> None:
    """Factory raises ValueError for unknown provider names."""
    from alayaos_core.llm.factory import create_llm_service

    settings = _make_settings(EXTRACTION_LLM_PROVIDER="openai", LLM_FALLBACK_PROVIDERS=[])
    with pytest.raises(ValueError, match="Unknown LLM provider: openai"):
        create_llm_service(settings)
