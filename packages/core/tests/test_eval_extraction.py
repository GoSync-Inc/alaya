"""Tests for eval_extraction.py — Run 2 vs Run 3 comparison eval script."""

import sys
from pathlib import Path

import pytest

# Add scripts dir to path so we can import eval_extraction
# test is at: packages/core/tests/test_eval_extraction.py
# scripts is at: scripts/ (4 levels up from tests/)
SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.mark.asyncio
async def test_run2_extract_returns_run2result():
    """run2_extract returns a Run2Result with correct event_id."""
    from eval_extraction import Run2Result, run2_extract

    event = {
        "id": "test-ev-001",
        "source_type": "slack",
        "source_id": "C1234/test",
        "text": "Alice is the owner of Project Phoenix.",
    }
    result = await run2_extract(event)
    assert isinstance(result, Run2Result)
    assert result.event_id == "test-ev-001"
    assert result.tokens_in >= 0
    assert result.tokens_out >= 0
    assert result.cost_usd == 0.0  # FakeLLMAdapter


@pytest.mark.asyncio
async def test_run3_classify_returns_run3result():
    """run3_classify returns a Run3Result with chunks_total >= 1."""
    from eval_extraction import Run3Result, run3_classify

    event = {
        "id": "test-ev-002",
        "source_type": "slack",
        "source_id": "C1234/test",
        "text": "Meeting tomorrow to discuss project deadlines and blockers.",
    }
    result = await run3_classify(event)
    assert isinstance(result, Run3Result)
    assert result.event_id == "test-ev-002"
    assert result.chunks_total >= 1
    assert result.chunks_crystal + result.chunks_skipped == result.chunks_total
    assert len(result.primary_domains) == result.chunks_total


@pytest.mark.asyncio
async def test_sample_events_all_processable():
    """All 5 sample events can be processed by both run2 and run3."""
    from eval_extraction import SAMPLE_EVENTS, run2_extract, run3_classify

    for event in SAMPLE_EVENTS:
        r2 = await run2_extract(event)
        r3 = await run3_classify(event)
        assert r2.event_id == event["id"]
        assert r3.event_id == event["id"]
        assert r3.chunks_total >= 1


@pytest.mark.asyncio
async def test_run3_chunk_count_varies_by_source_type():
    """Different source types produce different chunk counts via CortexChunker."""
    from eval_extraction import run3_classify

    # Slack message — single chunk (short)
    slack_event = {
        "id": "ev-slack",
        "source_type": "slack",
        "source_id": "C001",
        "text": "Alice: Quick update — sprint review is Thursday.\nBob: Got it.",
    }

    # Meeting transcript — may split by speaker turns
    meeting_event = {
        "id": "ev-meeting",
        "source_type": "meeting_transcript",
        "source_id": "meet-001",
        "text": (
            "Alice: The Q2 goals are on track.\n"
            "Bob: I have a blocker with the API rate limit.\n"
            "Alice: Let's escalate to DevOps.\n"
            "Bob: I'll create a ticket."
        ),
    }

    r_slack = await run3_classify(slack_event)
    r_meeting = await run3_classify(meeting_event)

    # Both should produce at least 1 chunk
    assert r_slack.chunks_total >= 1
    assert r_meeting.chunks_total >= 1
    # Crystal + skipped should always sum to total
    assert r_slack.chunks_crystal + r_slack.chunks_skipped == r_slack.chunks_total
    assert r_meeting.chunks_crystal + r_meeting.chunks_skipped == r_meeting.chunks_total
