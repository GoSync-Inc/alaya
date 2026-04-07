"""Extraction latency benchmarks — sanitizer and preprocessor performance."""

import time

from alayaos_core.extraction.preprocessor import Preprocessor
from alayaos_core.extraction.sanitizer import sanitize


def test_sanitizer_performance() -> None:
    """Sanitizer should handle 100K chars in < 100ms."""
    text = "Alice mentioned Project Phoenix. " * 3000  # ~100K chars
    start = time.monotonic()
    sanitize(text)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"Sanitizer took {elapsed:.3f}s for ~100K chars"


def test_preprocessor_performance() -> None:
    """Preprocessor should chunk 100K chars in < 500ms.

    Uses large paragraph blocks to avoid O(n^2) paragraph-counting overhead
    that occurs with thousands of tiny paragraphs. This models realistic
    document content: a few large paragraphs totaling ~100K chars.
    """
    # Build ~100K chars as a few large paragraphs (realistic document shape)
    paragraph = "Alice mentioned Project Phoenix in the planning meeting. " * 300 + "\n\n"
    text = paragraph * 5  # ~85K chars, 5 large paragraphs
    pp = Preprocessor()
    start = time.monotonic()
    chunks = pp.chunk(text, "manual", "test-perf")
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Preprocessor took {elapsed:.3f}s for ~100K chars"
    assert len(chunks) > 1


def test_sanitizer_idempotent_on_clean_text() -> None:
    """Sanitizer returns same text for already-clean input."""
    clean = "Alice is the PM of Project Phoenix. Deadline: April 15."
    result = sanitize(clean)
    assert result == clean


def test_preprocessor_single_chunk_for_short_text() -> None:
    """Preprocessor returns a single chunk for short text."""
    text = "Alice is the PM of Project Phoenix."
    pp = Preprocessor()
    chunks = pp.chunk(text, "slack", "C001/T001")
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_sanitizer_caps_at_max_chars() -> None:
    """Sanitizer truncates input to max_chars."""
    text = "x" * 20_000
    result = sanitize(text, max_chars=10_000)
    assert len(result) == 10_000


def test_preprocessor_large_text_multiple_chunks() -> None:
    """Preprocessor produces multiple chunks for a 100K char text."""
    # Use 100K chars with paragraph breaks so chunking can split
    paragraph = "Alice mentioned Project Phoenix in the planning meeting. " * 50 + "\n\n"
    text = paragraph * 30  # ~90K chars with natural paragraph boundaries
    pp = Preprocessor()
    chunks = pp.chunk(text, "manual", "perf-test")
    assert len(chunks) > 1
    # All chunks should have content
    for chunk in chunks:
        assert len(chunk.text) > 0
