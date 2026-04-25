"""LLM service interface and shared types."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMUsage(BaseModel):
    tokens_in: int  # = usage.input_tokens (non-cached input, per Anthropic)
    tokens_out: int  # = usage.output_tokens
    tokens_cached: int  # = usage.cache_read_input_tokens (cache hits)
    cost_usd: float
    cache_write_5m_tokens: int = 0  # = usage.cache_creation.ephemeral_5m_input_tokens
    cache_write_1h_tokens: int = 0  # = usage.cache_creation.ephemeral_1h_input_tokens

    @property
    def total_input(self) -> int:
        """Total input tokens across all classes (non-cached + cache-read + cache-written)."""
        return self.tokens_in + self.tokens_cached + self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def cache_hit_ratio(self) -> float:
        """Fraction of total input tokens served from cache."""
        return self.tokens_cached / self.total_input if self.total_input > 0 else 0.0


class LLMServiceInterface(Protocol):
    async def extract(
        self,
        text: str,
        system_prompt: str,
        response_model: type[T],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        stage: str = "unknown",
    ) -> tuple[T, LLMUsage]: ...
