"""Regression tests for AnthropicAdapter coercion behaviour."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm import anthropic as _anthropic_module
from alayaos_core.llm.anthropic import AnthropicAdapter


class _OptListModel(BaseModel):
    entries: list[str] | None = None


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


def test_coerce_list_strings_pep604_optional_list() -> None:
    """_coerce_list_strings must handle PEP 604 list[X] | None annotations."""
    data: dict[str, object] = {"entries": '["a", "b"]'}
    result = _anthropic_module._coerce_list_strings(data, _OptListModel)  # type: ignore[attr-defined]
    assert result["entries"] == ["a", "b"]


def test_coerce_list_strings_non_array_json_string_left_unchanged() -> None:
    """A JSON-encoded non-array string must be left unchanged, causing Pydantic to raise."""
    data: dict[str, object] = {"entries": '"single string"'}
    result = _anthropic_module._coerce_list_strings(data, _OptListModel)  # type: ignore[attr-defined]
    # Value must not have been replaced with a list
    assert result["entries"] == '"single string"'
    # Pydantic must reject the value with a list_type error
    with pytest.raises(ValidationError) as exc_info:
        _OptListModel.model_validate(result)
    errors = exc_info.value.errors()
    assert any(e["type"] == "list_type" for e in errors)
