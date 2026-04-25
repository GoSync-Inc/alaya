"""Single source of truth for Anthropic model pricing.

Pricing multipliers (per Anthropic published rates, 2026):
  - Cache reads:           0.10× base input rate
  - Cache writes 5-min TTL: 1.25× base input rate
  - Cache writes 1-hour TTL: 2.00× base input rate

Do NOT use cache_creation_input_tokens (the aggregated scalar) for cost math.
Always use the TTL-split fields ephemeral_5m_input_tokens / ephemeral_1h_input_tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alayaos_core.llm.interface import LLMUsage


@dataclass(frozen=True)
class ModelPrice:
    """Per-model pricing in USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_5m_per_mtok: float
    cache_write_1h_per_mtok: float

    def cost_usd(self, usage: LLMUsage) -> float:
        """Compute total cost from granular LLMUsage fields."""
        return (
            usage.tokens_in * self.input_per_mtok / 1_000_000
            + usage.tokens_out * self.output_per_mtok / 1_000_000
            + usage.tokens_cached * self.cache_read_per_mtok / 1_000_000
            + usage.cache_write_5m_tokens * self.cache_write_5m_per_mtok / 1_000_000
            + usage.cache_write_1h_tokens * self.cache_write_1h_per_mtok / 1_000_000
        )


# Published Anthropic rates (USD per 1M tokens), 2026.
# cache_read = 0.10× input; cache_write_5m = 1.25× input; cache_write_1h = 2.00× input.
PRICING: dict[str, ModelPrice] = {
    "claude-haiku-4-5-20251001": ModelPrice(
        input_per_mtok=0.80,
        output_per_mtok=4.0,
        cache_read_per_mtok=0.08,
        cache_write_5m_per_mtok=1.00,
        cache_write_1h_per_mtok=1.60,
    ),
    "claude-sonnet-4-20250514": ModelPrice(
        input_per_mtok=3.00,
        output_per_mtok=15.0,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=3.75,
        cache_write_1h_per_mtok=6.00,
    ),
    "claude-sonnet-4-6-20250514": ModelPrice(
        input_per_mtok=3.00,
        output_per_mtok=15.0,
        cache_read_per_mtok=0.30,
        cache_write_5m_per_mtok=3.75,
        cache_write_1h_per_mtok=6.00,
    ),
    "claude-opus-4-20250514": ModelPrice(
        input_per_mtok=15.0,
        output_per_mtok=75.0,
        cache_read_per_mtok=1.50,
        cache_write_5m_per_mtok=18.75,
        cache_write_1h_per_mtok=30.0,
    ),
    "claude-opus-4-6-20250514": ModelPrice(
        input_per_mtok=15.0,
        output_per_mtok=75.0,
        cache_read_per_mtok=1.50,
        cache_write_5m_per_mtok=18.75,
        cache_write_1h_per_mtok=30.0,
    ),
}

# Fallback: Sonnet-4.6 pricing when model is unknown.
DEFAULT_PRICING = PRICING["claude-sonnet-4-6-20250514"]

# Anthropic prompt-cache minimum input size (in tokens).
# Prompts below this threshold return zero cache_* counters regardless of cache_control.
MODEL_CACHE_MINIMUM: dict[str, int] = {
    "claude-haiku-4-5-20251001": 4096,
    "claude-sonnet-4-20250514": 2048,
    "claude-sonnet-4-6-20250514": 2048,
    "claude-opus-4-20250514": 2048,
    "claude-opus-4-6-20250514": 2048,
}
