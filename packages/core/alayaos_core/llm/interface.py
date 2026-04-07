"""LLM service interface and shared types."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMUsage(BaseModel):
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    cost_usd: float


class LLMServiceInterface(Protocol):
    async def extract(
        self,
        text: str,
        system_prompt: str,
        response_model: type[T],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[T, LLMUsage]: ...
