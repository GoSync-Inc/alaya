"""Anthropic LLM adapter using messages.parse() for structured output."""

import anthropic

from alayaos_core.llm.interface import LLMUsage, T


class AnthropicAdapter:
    """Anthropic LLM adapter using messages.parse() for structured output."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract(
        self,
        text: str,
        system_prompt: str,
        response_model: type[T],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[T, LLMUsage]:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": text}],
            response_model=response_model,
        )
        usage = LLMUsage(
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            tokens_cached=getattr(response.usage, "cache_read_input_tokens", 0),
            cost_usd=self._calculate_cost(response.usage),
        )
        return response.parsed, usage

    def _calculate_cost(self, usage: object) -> float:
        # Anthropic pricing per 1M tokens (Claude Sonnet 4)
        input_tokens: int = getattr(usage, "input_tokens", 0)
        output_tokens: int = getattr(usage, "output_tokens", 0)
        cached_tokens: int = getattr(usage, "cache_read_input_tokens", 0)
        input_cost = input_tokens * 3.0 / 1_000_000
        output_cost = output_tokens * 15.0 / 1_000_000
        cached_cost = cached_tokens * 0.3 / 1_000_000
        return input_cost + output_cost + cached_cost
