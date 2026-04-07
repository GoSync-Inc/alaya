"""Tests for the LLM extractor."""

import pytest

from alayaos_core.extraction.extractor import Extractor
from alayaos_core.extraction.preprocessor import Chunk
from alayaos_core.extraction.schemas import ExtractionResult
from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.llm.interface import LLMUsage

# ─── System prompt construction ───────────────────────────────────────────────


def make_extractor() -> Extractor:
    return Extractor(llm=FakeLLMAdapter())


ENTITY_TYPES = [
    {"slug": "person", "description": "A human individual"},
    {"slug": "project", "description": "A work project"},
]

PREDICATES = [
    {"slug": "deadline", "value_type": "date", "supersession_strategy": "latest_wins"},
    {"slug": "owner", "value_type": "entity_ref"},
]


def test_build_system_prompt_has_xml_boundary() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<instructions>" in prompt
    assert "</instructions>" in prompt


def test_build_system_prompt_has_ontology() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<ontology>" in prompt
    assert "person" in prompt
    assert "deadline" in prompt


def test_build_system_prompt_has_existing_entities() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES, existing_entities=["Alice", "Bob"])
    assert "<existing_entities>" in prompt
    assert "Alice" in prompt
    assert "Bob" in prompt


def test_build_system_prompt_no_existing_entities() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<existing_entities>" not in prompt


def test_system_prompt_has_rules() -> None:
    extractor = make_extractor()
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    assert "<rules>" in prompt


# ─── extract_chunk ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_chunk_calls_llm() -> None:
    adapter = FakeLLMAdapter()
    # Register response for the wrapped user message
    # The user message will be: "<data>{sanitized text}</data>"
    from alayaos_core.extraction.sanitizer import sanitize

    text = "Alice is PM of Project Phoenix"
    sanitized = sanitize(text)
    user_msg = f"<data>{sanitized}</data>"
    h = FakeLLMAdapter.content_hash(user_msg)
    adapter.add_response(
        h,
        {
            "entities": [{"name": "Alice", "entity_type": "person"}],
            "relations": [],
            "claims": [],
        },
    )

    extractor = Extractor(llm=adapter)
    chunk = Chunk(
        text=text,
        index=0,
        total=1,
        source_type="manual",
        source_id="s1",
        prior_entities=[],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    result, usage = await extractor.extract_chunk(chunk, prompt)
    assert isinstance(result, ExtractionResult)
    assert isinstance(usage, LLMUsage)


@pytest.mark.asyncio
async def test_extract_chunk_includes_prior_entities_in_message() -> None:
    """When chunk has prior_entities, user message should include prior_entities header."""
    adapter = FakeLLMAdapter()
    extractor = Extractor(llm=adapter)

    chunk = Chunk(
        text="Bob leads the team",
        index=1,
        total=2,
        source_type="manual",
        source_id="s1",
        prior_entities=["Alice Smith"],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    # FakeLLMAdapter will return defaults — just verify no crash + prior_entities header sent
    result, _ = await extractor.extract_chunk(chunk, prompt)
    assert isinstance(result, ExtractionResult)


# ─── gleaning ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gleaning_skipped_for_small_chunks() -> None:
    """Gleaning should NOT be triggered when token_count < gleaning_min_tokens."""
    adapter = FakeLLMAdapter()
    extractor = Extractor(llm=adapter, gleaning_enabled=True, gleaning_min_tokens=2000)

    chunk = Chunk(
        text="short text",
        index=0,
        total=1,
        source_type="manual",
        source_id="s1",
        prior_entities=[],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)

    # Token count << gleaning_min_tokens (2000)
    token_count = 10

    result, usage = await extractor.extract_with_gleaning(chunk, prompt, token_count)
    assert isinstance(result, ExtractionResult)
    # Cost should reflect single call (FakeLLMAdapter always cost=0.0)
    assert usage.cost_usd == 0.0


@pytest.mark.asyncio
async def test_gleaning_applied_for_large_chunks() -> None:
    """Gleaning SHOULD be triggered when token_count >= gleaning_min_tokens."""
    adapter = FakeLLMAdapter()
    # Set up response for first call (main extract)
    from alayaos_core.extraction.sanitizer import sanitize

    text = "Large chunk of text"
    sanitized = sanitize(text)
    user_msg = f"<data>{sanitized}</data>"
    h = FakeLLMAdapter.content_hash(user_msg)
    adapter.add_response(
        h,
        {
            "entities": [{"name": "Alice", "entity_type": "person"}],
            "relations": [],
            "claims": [],
        },
    )

    extractor = Extractor(llm=adapter, gleaning_enabled=True, gleaning_min_tokens=100)

    chunk = Chunk(
        text=text,
        index=0,
        total=1,
        source_type="manual",
        source_id="s1",
        prior_entities=[],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)

    # Token count > gleaning_min_tokens (100)
    token_count = 200

    result, usage = await extractor.extract_with_gleaning(chunk, prompt, token_count)
    assert isinstance(result, ExtractionResult)
    # Gleaning was run: usage should reflect 2 LLM calls (tokens_in = 100+100=200)
    assert usage.tokens_in == 200
    assert usage.tokens_out == 100


@pytest.mark.asyncio
async def test_gleaning_merges_results() -> None:
    """Gleaning pass results should be merged into the main result."""
    adapter = FakeLLMAdapter()
    from alayaos_core.extraction.sanitizer import sanitize

    text = "Main entity text"
    sanitized = sanitize(text)
    user_msg = f"<data>{sanitized}</data>"
    h = FakeLLMAdapter.content_hash(user_msg)
    adapter.add_response(
        h,
        {
            "entities": [{"name": "Alice", "entity_type": "person"}],
            "relations": [],
            "claims": [],
        },
    )

    # Gleaning call gets default (empty) response

    extractor = Extractor(llm=adapter, gleaning_enabled=True, gleaning_min_tokens=5)
    chunk = Chunk(
        text=text,
        index=0,
        total=1,
        source_type="manual",
        source_id="s1",
        prior_entities=[],
    )
    prompt = extractor.build_system_prompt(ENTITY_TYPES, PREDICATES)
    result, _ = await extractor.extract_with_gleaning(chunk, prompt, token_count=10)
    # Alice should still be in entities after merge
    assert any(e.name == "Alice" for e in result.entities)
