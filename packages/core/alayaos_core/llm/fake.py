"""Deterministic LLM adapter for testing. Returns pre-defined responses from fixture files."""

import hashlib
import json
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from alayaos_core.llm.interface import LLMUsage, T


class FakeLLMAdapter:
    """Deterministic LLM adapter for testing. Returns pre-defined responses from fixture files."""

    def __init__(self, fixtures_dir: Path | str | None = None) -> None:
        self._fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        self._responses: dict[str, dict] = {}

    def add_response(self, content_hash: str, response_data: dict) -> None:
        """Register a response for a given content hash."""
        self._responses[content_hash] = response_data

    @staticmethod
    def content_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def extract(
        self,
        text: str,
        system_prompt: str,
        response_model: type[T],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[T, LLMUsage]:
        h = self.content_hash(text)

        # Try in-memory first
        if h in self._responses:
            data = self._responses[h]
        elif self._fixtures_dir:
            fixture_path = self._fixtures_dir / f"{h}.json"
            if fixture_path.exists():
                data = json.loads(fixture_path.read_text())
            else:
                data = self._default_response(response_model)
        else:
            data = self._default_response(response_model)

        result = response_model.model_validate(data)
        usage = LLMUsage(tokens_in=100, tokens_out=50, tokens_cached=0, cost_usd=0.0)
        return result, usage

    # Model-specific overrides for realistic fake responses
    _MODEL_OVERRIDES: ClassVar[dict[str, dict]] = {
        "DomainScores": {
            "project": 0.6,
            "people": 0.4,
            "engineering": 0.3,
            "knowledge": 0.2,
        },
        "AskResponseModel": {
            "answer": "Based on the available context, here is what I found.",
            "answerable": True,
            "citations": [],
        },
    }

    @classmethod
    def _default_response(cls, response_model: type[BaseModel]) -> dict:
        """Return empty/minimal valid response for any Pydantic model."""
        # Check for model-specific overrides (e.g., DomainScores needs non-zero values)
        model_name = response_model.__name__
        if model_name in cls._MODEL_OVERRIDES:
            return cls._MODEL_OVERRIDES[model_name]

        # Build a minimal valid instance using model defaults
        fields = response_model.model_fields
        data: dict = {}
        for name, field_info in fields.items():
            if field_info.default is not PydanticUndefined and field_info.default is not None:
                data[name] = field_info.default
            elif field_info.default_factory is not None:
                data[name] = field_info.default_factory()
            # Skip required fields with no default — let model_validate handle them
        return data
