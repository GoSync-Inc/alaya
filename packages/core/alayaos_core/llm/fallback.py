"""LLM adapter with automatic fallback across providers."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from alayaos_core.llm.interface import LLMServiceInterface, LLMUsage, T

log = structlog.get_logger()


class FallbackLLMAdapter:
    """Wraps a primary LLM adapter with fallback alternatives.

    Tries primary first. On any exception, tries fallbacks in order.
    Raises the last exception if all providers fail.
    """

    def __init__(self, primary: LLMServiceInterface, fallbacks: list[LLMServiceInterface]) -> None:
        self._primary = primary
        self._fallbacks = fallbacks

    async def extract(
        self,
        text: str,
        system_prompt: str,
        response_model: type[T],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[T, LLMUsage]:
        providers = [self._primary, *self._fallbacks]
        last_error: Exception | None = None

        for i, provider in enumerate(providers):
            try:
                result = await provider.extract(
                    text=text,
                    system_prompt=system_prompt,
                    response_model=response_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if i > 0:
                    log.info("llm_fallback_used", provider_index=i, provider=type(provider).__name__)
                return result
            except Exception as exc:
                last_error = exc
                log.warning(
                    "llm_provider_failed",
                    provider_index=i,
                    provider=type(provider).__name__,
                    error=str(exc),
                )

        raise last_error  # type: ignore[misc]
