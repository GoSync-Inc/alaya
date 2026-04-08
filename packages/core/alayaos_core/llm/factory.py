"""Factory for creating LLM service instances from configuration."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from alayaos_core.config import Settings

if TYPE_CHECKING:
    from alayaos_core.llm.interface import LLMServiceInterface

log = structlog.get_logger()


def create_llm_service(settings: Settings | None = None) -> LLMServiceInterface:
    """Create an LLM service based on configuration.

    Reads EXTRACTION_LLM_PROVIDER and LLM_FALLBACK_PROVIDERS from settings.
    Returns a FallbackLLMAdapter if fallbacks are configured, otherwise returns
    the primary adapter directly.
    """
    if settings is None:
        settings = Settings()

    primary = _create_adapter(settings.EXTRACTION_LLM_PROVIDER, settings)

    fallback_names = settings.LLM_FALLBACK_PROVIDERS
    if not fallback_names:
        return primary

    from alayaos_core.llm.fallback import FallbackLLMAdapter

    fallbacks = [_create_adapter(name, settings) for name in fallback_names]
    return FallbackLLMAdapter(primary=primary, fallbacks=fallbacks)


def _create_adapter(provider: str, settings: Settings) -> LLMServiceInterface:
    """Create a single LLM adapter by provider name."""
    if provider == "anthropic":
        from alayaos_core.llm.anthropic import AnthropicAdapter

        return AnthropicAdapter(
            api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
            model=settings.ANTHROPIC_MODEL,
        )
    elif provider == "fake":
        from alayaos_core.llm.fake import FakeLLMAdapter

        return FakeLLMAdapter()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
