"""Regression tests for AnthropicAdapter coercion behaviour."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm.anthropic import AnthropicAdapter


def _build_mock_tool_response(tool_input: dict[str, object]) -> MagicMock:
    """Build a mock Anthropic Message with one tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input

    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 5
    usage.cache_read_input_tokens = 0

    response = MagicMock()
    response.content = [block]
    response.usage = usage
    return response


def _mock_client(mock_response: MagicMock) -> MagicMock:
    """Build a mock AsyncAnthropic client whose messages.create returns mock_response."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=mock_response)
    return client


@pytest.mark.asyncio
async def test_adapter_coerces_json_string_list_for_entities_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter must parse a JSON-encoded list string into a real list before validation."""
    mock_response = _build_mock_tool_response(
        {
            "entities": '[{"name": "Alice", "entity_type": "person"}]',
            "claims": [],
            "relations": [],
        }
    )
    adapter = AnthropicAdapter("fake-key", "claude-sonnet-4-20250514")
    adapter._client = _mock_client(mock_response)  # type: ignore[misc]

    result, _ = await adapter.extract("x", "y", ExtractionResult)

    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"
