"""Tests for llm/pricing.py — single source of truth for model costs."""

import pytest

from alayaos_core.llm.interface import LLMUsage
from alayaos_core.llm.pricing import DEFAULT_PRICING, MODEL_CACHE_MINIMUM, PRICING, ModelPrice


class TestModelPrice:
    def test_cost_usd_input_only(self) -> None:
        """Pure input cost with no cache."""
        price = ModelPrice(
            input_per_mtok=3.0,
            output_per_mtok=15.0,
            cache_read_per_mtok=0.30,
            cache_write_5m_per_mtok=3.75,
            cache_write_1h_per_mtok=6.00,
        )
        usage = LLMUsage(tokens_in=1_000_000, tokens_out=0, tokens_cached=0, cost_usd=0.0)
        assert price.cost_usd(usage) == pytest.approx(3.0)

    def test_cost_usd_output_only(self) -> None:
        price = ModelPrice(
            input_per_mtok=3.0,
            output_per_mtok=15.0,
            cache_read_per_mtok=0.30,
            cache_write_5m_per_mtok=3.75,
            cache_write_1h_per_mtok=6.00,
        )
        usage = LLMUsage(tokens_in=0, tokens_out=1_000_000, tokens_cached=0, cost_usd=0.0)
        assert price.cost_usd(usage) == pytest.approx(15.0)

    def test_cost_usd_cache_read(self) -> None:
        """Cache read is 0.10× input rate (cache_read_per_mtok = 0.30 for Sonnet, input = 3.0)."""
        price = PRICING["claude-sonnet-4-6-20250514"]
        usage = LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=1_000_000, cost_usd=0.0)
        assert price.cost_usd(usage) == pytest.approx(0.30)

    def test_cost_usd_cache_write_5m(self) -> None:
        """Cache write 5m is 1.25× input rate (3.75 for Sonnet)."""
        price = PRICING["claude-sonnet-4-6-20250514"]
        usage = LLMUsage(
            tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0, cache_write_5m_tokens=1_000_000
        )
        assert price.cost_usd(usage) == pytest.approx(3.75)

    def test_cost_usd_cache_write_1h(self) -> None:
        """Cache write 1h is 2.0× input rate (6.0 for Sonnet)."""
        price = PRICING["claude-sonnet-4-6-20250514"]
        usage = LLMUsage(
            tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0, cache_write_1h_tokens=1_000_000
        )
        assert price.cost_usd(usage) == pytest.approx(6.00)

    def test_cost_usd_combined_all_classes(self) -> None:
        """All token classes combined produce additive cost."""
        price = PRICING["claude-sonnet-4-6-20250514"]
        usage = LLMUsage(
            tokens_in=100_000,
            tokens_out=50_000,
            tokens_cached=200_000,
            cost_usd=0.0,
            cache_write_5m_tokens=150_000,
            cache_write_1h_tokens=50_000,
        )
        expected = (
            100_000 * 3.0 / 1_000_000
            + 50_000 * 15.0 / 1_000_000
            + 200_000 * 0.30 / 1_000_000
            + 150_000 * 3.75 / 1_000_000
            + 50_000 * 6.00 / 1_000_000
        )
        assert price.cost_usd(usage) == pytest.approx(expected, rel=1e-9)


class TestPricingDict:
    def test_all_models_present(self) -> None:
        expected_models = {
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-6-20250514",
            "claude-opus-4-20250514",
            "claude-opus-4-6-20250514",
        }
        assert set(PRICING.keys()) == expected_models

    def test_haiku_input_rate(self) -> None:
        assert PRICING["claude-haiku-4-5-20251001"].input_per_mtok == 0.80

    def test_haiku_cache_read_is_tenth_of_input(self) -> None:
        h = PRICING["claude-haiku-4-5-20251001"]
        assert h.cache_read_per_mtok == pytest.approx(h.input_per_mtok * 0.10)

    def test_sonnet_cache_write_5m_is_125x_input(self) -> None:
        s = PRICING["claude-sonnet-4-6-20250514"]
        assert s.cache_write_5m_per_mtok == pytest.approx(s.input_per_mtok * 1.25)

    def test_sonnet_cache_write_1h_is_2x_input(self) -> None:
        s = PRICING["claude-sonnet-4-6-20250514"]
        assert s.cache_write_1h_per_mtok == pytest.approx(s.input_per_mtok * 2.0)

    def test_opus_pricing(self) -> None:
        o = PRICING["claude-opus-4-6-20250514"]
        assert o.input_per_mtok == 15.0
        assert o.output_per_mtok == 75.0

    def test_default_pricing_is_sonnet(self) -> None:
        assert DEFAULT_PRICING is PRICING["claude-sonnet-4-6-20250514"]

    def test_default_pricing_used_for_unknown_model(self) -> None:
        from alayaos_core.llm.pricing import DEFAULT_PRICING as dp

        price = PRICING.get("unknown-model-xyz", dp)
        assert price is dp


class TestModelCacheMinimum:
    def test_haiku_minimum_is_4096(self) -> None:
        assert MODEL_CACHE_MINIMUM["claude-haiku-4-5-20251001"] == 4096

    def test_sonnet_minimum_is_2048(self) -> None:
        assert MODEL_CACHE_MINIMUM["claude-sonnet-4-6-20250514"] == 2048

    def test_all_models_have_minimum(self) -> None:
        assert set(MODEL_CACHE_MINIMUM.keys()) == set(PRICING.keys())
