"""Anthropic LLM adapter using tool-based structured output."""

import anthropic

from alayaos_core.llm.interface import LLMUsage, T

# Pricing per 1M tokens
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cached": 0.3},
    "claude-sonnet-4-6-20250514": {"input": 3.0, "output": 15.0, "cached": 0.3},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cached": 0.08},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0, "cached": 1.5},
    "claude-opus-4-6-20250514": {"input": 15.0, "output": 75.0, "cached": 1.5},
}
DEFAULT_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0, "cached": 0.3}  # Sonnet fallback


class AnthropicAdapter:
    """Anthropic LLM adapter using tool use for structured output."""

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
        # Build tool definition from Pydantic schema
        schema = response_model.model_json_schema()
        tool = {
            "name": "extract_result",
            "description": "Extract structured data from the input",
            "input_schema": schema,
        }

        response = await self._client.messages.create(
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
            tools=[tool],
            tool_choice={"type": "tool", "name": "extract_result"},
        )

        # Parse tool use result
        tool_input = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            raise ValueError("Model did not return tool use result")

        result = response_model.model_validate(tool_input)
        usage = LLMUsage(
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            tokens_cached=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cost_usd=self._calculate_cost(response.usage),
        )
        return result, usage

    def _calculate_cost(self, usage: object) -> float:
        # Look up pricing for the current model, fall back to DEFAULT_PRICING
        pricing = PRICING.get(self._model, DEFAULT_PRICING)
        input_tokens: int = getattr(usage, "input_tokens", 0)
        output_tokens: int = getattr(usage, "output_tokens", 0)
        cached_tokens: int = getattr(usage, "cache_read_input_tokens", 0)
        input_cost = input_tokens * pricing["input"] / 1_000_000
        output_cost = output_tokens * pricing["output"] / 1_000_000
        cached_cost = cached_tokens * pricing["cached"] / 1_000_000
        return input_cost + output_cost + cached_cost
