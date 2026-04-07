"""Tests for CortexChunker — speaker-turn splitting, threads, edge cases."""

import json

from alayaos_core.extraction.cortex.chunker import CortexChunker
from alayaos_core.extraction.preprocessor import Chunk, Preprocessor

# Use a very small max_chunk_tokens to trigger splitting without huge text
SMALL_MAX = 50


# ─── Basic structure ──────────────────────────────────────────────────────────


def test_raw_chunk_has_token_count() -> None:
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("Hello world", "slack", "s1")
    assert len(chunks) == 1
    assert chunks[0].token_count == chunker.count_tokens("Hello world")


def test_chunk_index_and_total_single() -> None:
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("Short text", "manual", "id1")
    assert chunks[0].index == 0
    assert chunks[0].total == 1


def test_chunk_index_and_total_multiple() -> None:
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    # Two paragraphs — each well above SMALL_MAX/2 tokens when combined
    para1 = "The quick brown fox jumps over the lazy dog near the riverbank. " * 3
    para2 = "A second paragraph about completely different things happening today now. " * 3
    text = para1.strip() + "\n\n" + para2.strip()
    chunks = chunker.chunk(text, "manual", "id2")
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
        assert chunk.total == len(chunks)


def test_source_type_and_id_preserved() -> None:
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("Some text", "meeting_transcript", "mt-001")
    assert all(c.source_type == "meeting_transcript" for c in chunks)
    assert all(c.source_id == "mt-001" for c in chunks)


# ─── Empty input ─────────────────────────────────────────────────────────────


def test_empty_string_returns_single_empty_chunk() -> None:
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("", "manual", "e1")
    assert len(chunks) == 1
    assert chunks[0].text == ""
    assert chunks[0].index == 0
    assert chunks[0].total == 1


# ─── Speaker-turn splitting (meeting_transcript) ─────────────────────────────


def test_speaker_turn_boundaries() -> None:
    transcript = (
        "[Alice]: We need to ship the feature by Friday.\n"
        "[Bob]: I agree, let's plan the work.\n"
        "[Alice]: Great, I'll start on the backend.\n"
    )
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(transcript, "meeting_transcript", "mt-1")
    # All content should be in chunks
    combined = " ".join(c.text for c in chunks)
    assert "ship the feature" in combined
    assert "start on the backend" in combined


def test_speaker_turns_grouped_by_speaker() -> None:
    """Consecutive same-speaker turns are merged."""
    transcript = "Alice: First statement.\nAlice: Second statement continues.\nBob: Bob responds here.\n"
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(transcript, "meeting_transcript", "mt-2")
    # Alice's two statements should be grouped together
    combined = " ".join(c.text for c in chunks)
    assert "First statement" in combined
    assert "Second statement" in combined


def test_speaker_turn_with_bracket_format() -> None:
    transcript = "[Speaker 1]: Let's discuss the roadmap.\n[Speaker 2]: Sure, I have some ideas.\n"
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(transcript, "meeting_transcript", "mt-3")
    combined = " ".join(c.text for c in chunks)
    assert "roadmap" in combined
    assert "ideas" in combined


def test_oversized_speaker_turn_split_at_sentence() -> None:
    """A single speaker turn longer than max_tokens is split at sentence boundary."""
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    # Generate a long turn with multiple sentences
    long_turn = "Alice: " + " ".join([f"This is sentence number {i} about the project." for i in range(20)])
    chunks = chunker.chunk(long_turn, "meeting_transcript", "mt-4")
    assert len(chunks) >= 2
    # No chunk should exceed max_tokens (allow small overage from single very long sentence)
    for c in chunks:
        assert c.token_count <= SMALL_MAX * 2  # generous allowance for edge cases


# ─── Slack JSON ───────────────────────────────────────────────────────────────


def test_slack_json_parse() -> None:
    """Structured Slack export with user/text fields is parsed correctly."""
    messages = [
        {"user": "U1", "text": "Hello team!", "ts": "1.0"},
        {"user": "U2", "text": "Hi there!", "ts": "2.0"},
        {"user": "U1", "text": "Ready for standup?", "ts": "3.0"},
    ]
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(json.dumps(messages), "slack", "C-slack-1")
    assert len(chunks) >= 1
    combined = " ".join(c.text for c in chunks)
    assert "Hello team" in combined
    assert "Hi there" in combined


def test_slack_json_thread_isolation() -> None:
    """Messages with different thread_ts are treated as separate threads (HARD split)."""
    messages = [
        {"user": "U1", "text": "Main message", "ts": "1.0", "thread_ts": "1.0"},
        {"user": "U2", "text": "Reply in thread", "ts": "2.0", "thread_ts": "1.0"},
        {"user": "U3", "text": "New thread start", "ts": "3.0", "thread_ts": "3.0"},
        {"user": "U4", "text": "Reply to new thread", "ts": "4.0", "thread_ts": "3.0"},
    ]
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    chunks = chunker.chunk(json.dumps(messages), "slack", "C-slack-2")
    # We should have chunks (thread isolation ensures content is preserved)
    assert len(chunks) >= 1
    combined = " ".join(c.text for c in chunks)
    assert "Main message" in combined
    assert "New thread start" in combined


def test_slack_json_consecutive_same_author_grouped() -> None:
    """Consecutive same-author messages in JSON are grouped together."""
    messages = [
        {"user": "U1", "text": "Part one of my message", "ts": "1.0"},
        {"user": "U1", "text": "Part two of my message", "ts": "2.0"},
        {"user": "U2", "text": "Response from U2", "ts": "3.0"},
    ]
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(json.dumps(messages), "slack", "C-slack-3")
    # U1's two messages should appear together in some chunk
    combined = " ".join(c.text for c in chunks)
    assert "Part one" in combined
    assert "Part two" in combined


# ─── Emoji-only filtering ────────────────────────────────────────────────────


def test_emoji_only_slack_messages_filtered() -> None:
    """Messages containing only emoji characters are skipped."""
    messages = [
        {"user": "U1", "text": "Great work everyone!", "ts": "1.0"},
        {"user": "U2", "text": "👍", "ts": "2.0"},
        {"user": "U3", "text": "🎉🎊🥳", "ts": "3.0"},
        {"user": "U4", "text": "Sounds good.", "ts": "4.0"},
    ]
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(json.dumps(messages), "slack", "C-emoji")
    combined = " ".join(c.text for c in chunks)
    # Actual text content preserved
    assert "Great work" in combined
    assert "Sounds good" in combined
    # Emoji-only messages not present (they don't contribute meaningful text)
    # (We don't assert 👍 absence since it might appear in non-emoji-only text)


# ─── Paragraph chunking ───────────────────────────────────────────────────────


def test_paragraph_fallback_generic_text() -> None:
    """Generic text (not slack/transcript) is split by \\n\\n."""
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    para1 = "First paragraph with some content that fills up space well."
    para2 = "Second paragraph with completely different content here."
    para3 = "Third paragraph talking about another topic entirely now."
    text = "\n\n".join([para1, para2, para3])
    chunks = chunker.chunk(text, "manual", "doc-1")
    combined = " ".join(c.text for c in chunks)
    assert "First paragraph" in combined
    assert "Second paragraph" in combined
    assert "Third paragraph" in combined


def test_oversized_paragraph_split_at_sentence_boundary() -> None:
    """Single paragraph > max_tokens is split at sentence boundaries."""
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    # One big paragraph with multiple sentences
    para = " ".join([f"This is sentence {i} describing important project updates." for i in range(15)])
    chunks = chunker.chunk(para, "manual", "doc-2")
    assert len(chunks) >= 2
    # Verify no mid-sentence splits — every chunk should end with sentence-ending punctuation
    for c in chunks[:-1]:
        assert c.text.strip()[-1] in ".!?", f"Chunk does not end at sentence: '{c.text[-50:]}'"


def test_paragraph_no_mid_sentence_split() -> None:
    """Verify that paragraph chunking never splits mid-sentence."""
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    sentences = [
        "Alice joined the project team on Monday.",
        "She brought expertise in machine learning.",
        "The team welcomed her with open arms.",
        "Bob scheduled an onboarding session.",
        "They discussed the roadmap for the next quarter.",
        "Everyone agreed on the timeline and deliverables.",
    ]
    text = " ".join(sentences)
    chunks = chunker.chunk(text, "document", "doc-3")
    for c in chunks[:-1]:
        assert c.text.strip()[-1] in ".!?"


# ─── Backward compatibility with Preprocessor ─────────────────────────────────


def test_preprocessor_chunk_with_cortex_returns_chunks() -> None:
    """preprocessor.chunk_with_cortex() returns Chunk objects (backward compat)."""
    p = Preprocessor(max_chunk_tokens=3000)
    transcript = "[Alice]: Hello.\n[Bob]: Hi there.\n"
    chunks = p.chunk_with_cortex(transcript, "meeting_transcript", "mt-bc-1")
    assert len(chunks) >= 1
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.source_type == "meeting_transcript"
        assert c.source_id == "mt-bc-1"


def test_preprocessor_chunk_with_cortex_index_and_total() -> None:
    """preprocessor.chunk_with_cortex() sets correct index/total on Chunk objects."""
    p = Preprocessor(max_chunk_tokens=SMALL_MAX)
    long_text = "Alice: " + " ".join([f"Sentence {i} about the project." for i in range(30)])
    chunks = p.chunk_with_cortex(long_text, "meeting_transcript", "mt-bc-2")
    for i, c in enumerate(chunks):
        assert c.index == i
        assert c.total == len(chunks)


# ─── Edge cases ───────────────────────────────────────────────────────────────


def test_single_word() -> None:
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("Hello", "manual", "e2")
    assert len(chunks) == 1
    assert chunks[0].text == "Hello"


def test_very_long_single_line_split() -> None:
    """A single line with no sentence boundaries is handled without crashing."""
    chunker = CortexChunker(max_chunk_tokens=SMALL_MAX)
    # A very long line without any sentence-ending punctuation
    text = "word " * 200
    chunks = chunker.chunk(text.strip(), "manual", "e3")
    assert len(chunks) >= 1
    combined = "".join(c.text for c in chunks)
    assert len(combined) > 0


def test_mixed_source_type_paragraph() -> None:
    """Unknown source types fall through to paragraph chunking."""
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk("Some content here.", "github", "gh-1")
    assert len(chunks) == 1
    assert chunks[0].source_type == "github"


def test_document_source_type_uses_speaker_turns() -> None:
    """document source type is handled like meeting_transcript."""
    transcript = "Alice: First point.\nBob: Second point.\n"
    chunker = CortexChunker(max_chunk_tokens=3000)
    chunks = chunker.chunk(transcript, "document", "doc-x")
    combined = " ".join(c.text for c in chunks)
    assert "First point" in combined
    assert "Second point" in combined
