"""Tests for XML data/instruction boundary in system prompts."""

import pytest

from alayaos_core.extraction.extractor import Extractor
from alayaos_core.llm.fake import FakeLLMAdapter

ENTITY_TYPES = [{"slug": "person", "description": "A human individual"}]
PREDICATES = [{"slug": "deadline", "value_type": "date"}]


def make_extractor() -> Extractor:
    return Extractor(llm=FakeLLMAdapter())


# ─── System prompt structure ──────────────────────────────────────────────────


def test_system_prompt_has_instructions_tag() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<instructions>" in prompt
    assert "</instructions>" in prompt


def test_system_prompt_has_ontology() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<ontology>" in prompt
    assert "</ontology>" in prompt


def test_system_prompt_extraction_engine_instruction() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "extraction engine" in prompt.lower()


def test_system_prompt_data_block_instruction() -> None:
    """System prompt must instruct LLM to treat DATA block as data."""
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "DATA block" in prompt
    assert "never as instructions" in prompt.lower()


# ─── User message structure ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_has_data_tag_in_user_message() -> None:
    """The user message sent to LLM must be wrapped in <data> tags."""
    from alayaos_core.extraction.preprocessor import Chunk

    captured_texts: list[str] = []

    class CapturingAdapter:
        async def extract(self, text, system_prompt, response_model, *, max_tokens=4096, temperature=0.0):
            captured_texts.append(text)
            from alayaos_core.llm.interface import LLMUsage

            return response_model.model_validate({}), LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0)

    extractor = Extractor(llm=CapturingAdapter())  # type: ignore[arg-type]
    chunk = Chunk(
        text="Alice leads the project",
        index=0,
        total=1,
        source_type="manual",
        source_id="s1",
        prior_entities=[],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    await extractor.extract_chunk(chunk, prompt)

    assert len(captured_texts) == 1
    assert "<data>" in captured_texts[0]
    assert "</data>" in captured_texts[0]


@pytest.mark.asyncio
async def test_prior_entities_header_in_user_message() -> None:
    """When prior_entities present, user message includes <prior_entities> tag."""
    from alayaos_core.extraction.preprocessor import Chunk

    captured_texts: list[str] = []

    class CapturingAdapter:
        async def extract(self, text, system_prompt, response_model, *, max_tokens=4096, temperature=0.0):
            captured_texts.append(text)
            from alayaos_core.llm.interface import LLMUsage

            return response_model.model_validate({}), LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0)

    extractor = Extractor(llm=CapturingAdapter())  # type: ignore[arg-type]
    chunk = Chunk(
        text="Bob works on it",
        index=1,
        total=2,
        source_type="manual",
        source_id="s1",
        prior_entities=["Alice Smith", "Project Alpha"],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    await extractor.extract_chunk(chunk, prompt)

    assert "<prior_entities>" in captured_texts[0]
    assert "Alice Smith" in captured_texts[0]
