"""Tests for CortexClassifier — scoring, verification, thresholds."""

import pytest

from alayaos_core.extraction.cortex.chunker import CortexChunker, RawChunk
from alayaos_core.extraction.cortex.classifier import CortexClassifier
from alayaos_core.extraction.cortex.schemas import DomainScores
from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.llm.interface import LLMUsage


def make_chunk(text: str, source_type: str = "manual", source_id: str = "test") -> RawChunk:
    chunker = CortexChunker(max_chunk_tokens=3000)
    return RawChunk(
        text=text,
        index=0,
        total=1,
        source_type=source_type,
        source_id=source_id,
        token_count=chunker.count_tokens(text),
    )


# ─── is_crystal ────────────────────────────────────────────────────────────────


def test_is_crystal_true_when_non_smalltalk_domain_above_threshold() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.1)
    scores = DomainScores(engineering=0.9)
    assert classifier.is_crystal(scores) is True


def test_is_crystal_false_when_all_scores_zero() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.1)
    scores = DomainScores()
    assert classifier.is_crystal(scores) is False


def test_is_crystal_false_when_only_smalltalk_is_high() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.1)
    scores = DomainScores(smalltalk=0.99)
    assert classifier.is_crystal(scores) is False


def test_is_crystal_true_when_project_at_threshold() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.5)
    scores = DomainScores(project=0.5)
    assert classifier.is_crystal(scores) is True


def test_is_crystal_false_when_project_below_threshold() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.5)
    scores = DomainScores(project=0.49)
    assert classifier.is_crystal(scores) is False


# ─── primary_domain ───────────────────────────────────────────────────────────


def test_primary_domain_returns_highest_score_domain() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    scores = DomainScores(engineering=0.8, project=0.3, people=0.1)
    assert classifier.primary_domain(scores) == "engineering"


def test_primary_domain_returns_smalltalk_when_highest() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    scores = DomainScores(smalltalk=0.9, engineering=0.1)
    assert classifier.primary_domain(scores) == "smalltalk"


def test_primary_domain_decision_wins() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    scores = DomainScores(decision=0.7, strategic=0.5, project=0.3)
    assert classifier.primary_domain(scores) == "decision"


# ─── classify (async) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_returns_domain_scores_and_usage() -> None:
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("We deployed the new microservice architecture today.")
    scores, usage = await classifier.classify(chunk)
    assert isinstance(scores, DomainScores)
    assert isinstance(usage, LLMUsage)


@pytest.mark.asyncio
async def test_classify_uses_registered_response() -> None:
    """FakeLLMAdapter returns specific scores when content hash matches."""
    llm = FakeLLMAdapter()
    engineering_text = "We refactored the database schema and updated the ORM models."
    h = FakeLLMAdapter.content_hash(engineering_text)
    llm.add_response(h, {"engineering": 0.9, "knowledge": 0.3})

    chunk = make_chunk(engineering_text)
    scores, _ = await classifier_for(llm).classify(chunk)
    assert scores.engineering == 0.9


def classifier_for(llm: FakeLLMAdapter, **kwargs) -> CortexClassifier:
    return CortexClassifier(llm, **kwargs)


# ─── verify (async) ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_changed_when_response_differs() -> None:
    """verify() returns changed=True when LLM returns different scores."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("We need to decide on the new API design.")

    # Get initial scores (defaults from FakeLLMAdapter = all 0.0)
    initial = DomainScores()

    # Register a different response for the verify call
    truncated = chunk.text  # short enough, no truncation
    verify_text = f"{truncated}\n\nPrevious classification: {initial.model_dump_json()}. Review and correct if needed."
    h = FakeLLMAdapter.content_hash(verify_text)
    llm.add_response(h, {"decision": 0.8, "engineering": 0.2})

    _, changed, usage = await classifier.verify(chunk, initial)
    assert changed is True
    assert isinstance(usage, LLMUsage)


@pytest.mark.asyncio
async def test_verify_not_changed_when_response_same() -> None:
    """verify() returns changed=False when LLM returns same scores."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("Hello there!")

    # FakeLLMAdapter default: all 0.0 for DomainScores
    initial = DomainScores()  # all 0.0

    # Don't register any special response — FakeLLMAdapter returns defaults (all 0.0)
    _, changed, _ = await classifier.verify(chunk, initial)
    # Both initial and verify return all zeros → changed=False
    assert changed is False


# ─── classify_and_verify (async) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_and_verify_combines_usage() -> None:
    """classify_and_verify sums tokens_in from both LLM calls."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("Team standup at 9am.")
    _, _, combined_usage = await classifier.classify_and_verify(chunk)
    # FakeLLMAdapter returns tokens_in=100 per call, so combined should be 200
    assert combined_usage.tokens_in == 200
    assert combined_usage.tokens_out == 100  # 50 + 50


@pytest.mark.asyncio
async def test_classify_and_verify_returns_final_scores() -> None:
    """classify_and_verify returns the verified scores (not initial)."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("Discussing Q3 OKRs and strategic vision.")

    # Register a special response for classify call
    h_classify = FakeLLMAdapter.content_hash(chunk.text)
    llm.add_response(h_classify, {"strategic": 0.9, "decision": 0.4})

    scores, _, _ = await classifier.classify_and_verify(chunk)
    assert isinstance(scores, DomainScores)


# ─── Token truncation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_truncates_long_text() -> None:
    """Long text is truncated to truncation_tokens before calling LLM."""
    import tiktoken

    llm = FakeLLMAdapter()
    truncation_tokens = 10
    classifier = CortexClassifier(llm, truncation_tokens=truncation_tokens)

    enc = tiktoken.get_encoding("cl100k_base")
    long_text = "word " * 100  # ~100 tokens
    chunk = make_chunk(long_text)

    # The classify call should use the truncated version (≤ 10 tokens)
    # Register response for truncated version
    truncated_tokens = enc.encode(long_text)[:truncation_tokens]
    truncated = enc.decode(truncated_tokens)
    h = FakeLLMAdapter.content_hash(truncated)
    llm.add_response(h, {"knowledge": 0.5})

    scores, _ = await classifier.classify(chunk)
    assert scores.knowledge == 0.5


# ─── Cyrillic / Russian text ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_russian_text_handled_without_error() -> None:
    """Classifier handles Russian/Cyrillic text without exceptions."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm)
    chunk = make_chunk("Привет, как дела? Всё хорошо у вас сегодня?")  # noqa: RUF001
    scores, usage = await classifier.classify(chunk)
    assert isinstance(scores, DomainScores)
    assert isinstance(usage, LLMUsage)


@pytest.mark.asyncio
async def test_russian_smalltalk_not_crystal_at_low_threshold() -> None:
    """Russian smalltalk text with smalltalk-only response is not crystal."""
    llm = FakeLLMAdapter()
    classifier = CortexClassifier(llm, crystal_threshold=0.5)
    chunk = make_chunk("Привет, как дела? Всё хорошо у вас сегодня?")  # noqa: RUF001

    h = FakeLLMAdapter.content_hash(chunk.text)
    llm.add_response(h, {"smalltalk": 0.95})

    scores, _ = await classifier.classify(chunk)
    assert classifier.is_crystal(scores) is False
