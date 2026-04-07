"""Tests for the source-aware text preprocessor."""

from alayaos_core.extraction.preprocessor import Preprocessor

# ─── Token counting ───────────────────────────────────────────────────────────


def test_token_counting() -> None:
    p = Preprocessor()
    # "hello world" is 2 tokens with cl100k_base
    count = p.count_tokens("hello world")
    assert count == 2


def test_token_counting_empty() -> None:
    p = Preprocessor()
    assert p.count_tokens("") == 0


# ─── Single chunk for small text ─────────────────────────────────────────────


def test_single_chunk_small_text() -> None:
    p = Preprocessor(max_chunk_tokens=3000)
    chunks = p.chunk("Short text", "manual", "src-001")
    assert len(chunks) == 1
    assert chunks[0].text == "Short text"
    assert chunks[0].index == 0
    assert chunks[0].total == 1
    assert chunks[0].source_type == "manual"
    assert chunks[0].source_id == "src-001"
    assert chunks[0].prior_entities == []


def test_single_chunk_has_correct_metadata() -> None:
    p = Preprocessor()
    chunks = p.chunk("Hello", "slack", "slack-001")
    assert chunks[0].source_type == "slack"
    assert chunks[0].source_id == "slack-001"


# ─── Multi-chunk for large text ──────────────────────────────────────────────


def test_multi_chunk_large_text() -> None:
    # Create text that exceeds 10 tokens but can be split by paragraphs
    p = Preprocessor(max_chunk_tokens=10)

    # Two paragraphs each ~6 tokens
    para1 = "The quick brown fox jumps"  # ~5 tokens
    para2 = "over the lazy sleeping dog"  # ~5 tokens
    text = para1 + "\n\n" + para2

    chunks = p.chunk(text, "manual", "src-002")
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
        assert chunk.total == len(chunks)


def test_multi_chunk_indices_correct() -> None:
    p = Preprocessor(max_chunk_tokens=5)
    paras = [f"Paragraph number {i} contains some words and text" for i in range(5)]
    text = "\n\n".join(paras)
    chunks = p.chunk(text, "manual", "src-003")
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
        assert chunk.total == len(chunks)


# ─── Entity propagation ───────────────────────────────────────────────────────


def test_entity_propagation() -> None:
    p = Preprocessor(max_chunk_tokens=5)
    paras = [f"Paragraph number {i} contains some words and text" for i in range(5)]
    text = "\n\n".join(paras)
    chunks = p.chunk(text, "manual", "src-004")
    assert len(chunks) > 1

    entities = ["Alice Smith", "Project Phoenix"]
    p.propagate_entities(chunks, entities)

    # First chunk has no prior entities
    assert chunks[0].prior_entities == []
    # All subsequent chunks have the entities
    for chunk in chunks[1:]:
        assert chunk.prior_entities == entities


def test_entity_propagation_single_chunk() -> None:
    p = Preprocessor()
    chunks = p.chunk("short", "manual", "x")
    p.propagate_entities(chunks, ["Alice"])
    # Single chunk: prior_entities stays empty (no "previous" chunk to propagate from)
    assert chunks[0].prior_entities == []


# ─── Source-type routing ─────────────────────────────────────────────────────


def test_slack_source_type_routed() -> None:
    p = Preprocessor()
    chunks = p.chunk("Slack message", "slack", "C123")
    assert all(c.source_type == "slack" for c in chunks)


def test_github_source_type_routed() -> None:
    p = Preprocessor()
    chunks = p.chunk("GitHub issue body", "github", "issue-42")
    assert all(c.source_type == "github" for c in chunks)


def test_linear_source_type_routed() -> None:
    p = Preprocessor()
    chunks = p.chunk("Linear ticket description", "linear", "LIN-123")
    assert all(c.source_type == "linear" for c in chunks)
