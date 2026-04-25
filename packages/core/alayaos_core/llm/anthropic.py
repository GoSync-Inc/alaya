"""Anthropic LLM adapter using tool-based structured output."""

from __future__ import annotations

import json
import types
import typing
from time import monotonic
from typing import TYPE_CHECKING

import anthropic

from alayaos_core.llm.interface import LLMUsage, T
from alayaos_core.llm.observability import log_cache_breakdown_unavailable, log_call_completed
from alayaos_core.llm.pricing import DEFAULT_PRICING, PRICING

if TYPE_CHECKING:
    from anthropic.types import ToolParam
    from pydantic import BaseModel

def _is_list_annotation(annotation: object) -> bool:
    """Return True if *annotation* represents a list type (including Optional[list[...]])."""
    origin = typing.get_origin(annotation)
    if origin is list:
        return True
    # Handle Union / Optional: e.g. list[X] | None (typing.Union or PEP 604 types.UnionType)
    if origin is typing.Union or isinstance(annotation, types.UnionType):
        for arg in typing.get_args(annotation):
            if typing.get_origin(arg) is list:
                return True
    return False


def _coerce_list_strings(data: dict[str, object], model: type[BaseModel]) -> dict[str, object]:
    """Return a shallow copy of *data* with JSON-string list fields parsed.

    For each top-level field in *model* whose annotation is ``list[...]`` (or
    ``list[...] | None``), if the corresponding value in *data* is a ``str``
    that can be parsed as a JSON array, replace it with the parsed list.
    Non-parseable strings and non-list parse results are left unchanged so
    that Pydantic can raise the appropriate validation error.
    """
    result = dict(data)
    for field_name, field_info in model.model_fields.items():
        if not _is_list_annotation(field_info.annotation):
            continue
        value = result.get(field_name)
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, list):
            result[field_name] = parsed
    return result


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
        stage: str = "unknown",
    ) -> tuple[T, LLMUsage]:
        # Build tool definition from Pydantic schema
        schema = response_model.model_json_schema()
        tool: ToolParam = {
            "name": "extract_result",
            "description": "Extract structured data from the input",
            "input_schema": schema,
        }

        _start = monotonic()
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
        latency_ms = int((monotonic() - _start) * 1000)

        # Parse tool use result
        tool_input = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            raise ValueError("Model did not return tool use result")

        tool_input = _coerce_list_strings(tool_input, response_model)
        result = response_model.model_validate(tool_input)

        raw_usage = response.usage

        # Granular cache-write fields — use TTL-split nested object, not the aggregated scalar.
        cache_creation = getattr(raw_usage, "cache_creation", None)
        if cache_creation is not None:
            cache_write_5m = getattr(cache_creation, "ephemeral_5m_input_tokens", 0) or 0
            cache_write_1h = getattr(cache_creation, "ephemeral_1h_input_tokens", 0) or 0
        else:
            # cache_creation absent — older SDK or unexpected response shape.
            # Emit once-per-process warning via observability module (once-per-model guard).
            log_cache_breakdown_unavailable(self._model)
            cache_write_5m = 0
            cache_write_1h = 0

        usage = LLMUsage(
            tokens_in=getattr(raw_usage, "input_tokens", 0),
            tokens_out=getattr(raw_usage, "output_tokens", 0),
            tokens_cached=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_write_5m_tokens=cache_write_5m,
            cache_write_1h_tokens=cache_write_1h,
            cost_usd=0.0,  # computed below after fields are set
        )
        # Compute cost using pricing.py (no buggy subtraction)
        price = PRICING.get(self._model, DEFAULT_PRICING)
        usage = usage.model_copy(update={"cost_usd": price.cost_usd(usage)})

        log_call_completed("llm.call_completed", self._model, stage, latency_ms, usage)

        return result, usage
