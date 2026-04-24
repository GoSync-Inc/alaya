"""Tests for extraction anomaly monitoring events."""

import structlog.testing

from alayaos_core.extraction.monitoring import (
    log_high_entity_count,
    log_injection_detected,
    log_low_confidence_batch,
    log_resolver_ambiguous,
)


def test_log_injection_detected_emits_warning() -> None:
    with structlog.testing.capture_logs() as cap:
        log_injection_detected(
            event_id="evt-1",
            pattern=r"ignore.*instructions",
            source_type="slack",
        )
    assert len(cap) == 1
    assert cap[0]["log_level"] == "warning"
    assert cap[0]["event"] == "extraction.injection_detected"
    assert cap[0]["event_id"] == "evt-1"
    assert cap[0]["source_type"] == "slack"


def test_log_injection_detected_includes_source_type() -> None:
    """source_type field is required per spec."""
    with structlog.testing.capture_logs() as cap:
        log_injection_detected(event_id="evt-2", pattern="p", source_type="github")
    assert cap[0]["source_type"] == "github"


def test_log_high_entity_count_above_threshold() -> None:
    with structlog.testing.capture_logs() as cap:
        log_high_entity_count(event_id="evt-3", count=51)
    assert len(cap) == 1
    assert cap[0]["log_level"] == "warning"
    assert cap[0]["event"] == "extraction.high_entity_count"
    assert cap[0]["count"] == 51
    assert cap[0]["threshold"] == 50


def test_log_high_entity_count_at_threshold_no_log() -> None:
    """Count equal to threshold must NOT emit a log."""
    with structlog.testing.capture_logs() as cap:
        log_high_entity_count(event_id="evt-4", count=50)
    assert len(cap) == 0


def test_log_high_entity_count_below_threshold_no_log() -> None:
    with structlog.testing.capture_logs() as cap:
        log_high_entity_count(event_id="evt-5", count=10)
    assert len(cap) == 0


def test_log_high_entity_count_custom_threshold() -> None:
    with structlog.testing.capture_logs() as cap:
        log_high_entity_count(event_id="evt-6", count=5, threshold=4)
    assert cap[0]["log_level"] == "warning"
    assert cap[0]["threshold"] == 4


def test_log_low_confidence_batch_below_threshold() -> None:
    with structlog.testing.capture_logs() as cap:
        log_low_confidence_batch(run_id="run-1", avg_confidence=0.3)
    assert len(cap) == 1
    assert cap[0]["log_level"] == "warning"
    assert cap[0]["event"] == "extraction.low_confidence_batch"
    assert cap[0]["run_id"] == "run-1"
    assert cap[0]["avg_confidence"] == 0.3


def test_log_low_confidence_batch_at_threshold_no_log() -> None:
    """avg_confidence equal to threshold must NOT emit a log."""
    with structlog.testing.capture_logs() as cap:
        log_low_confidence_batch(run_id="run-2", avg_confidence=0.6)
    assert len(cap) == 0


def test_log_low_confidence_batch_above_threshold_no_log() -> None:
    with structlog.testing.capture_logs() as cap:
        log_low_confidence_batch(run_id="run-3", avg_confidence=0.8)
    assert len(cap) == 0


def test_log_resolver_ambiguous_emits_info() -> None:
    with structlog.testing.capture_logs() as cap:
        log_resolver_ambiguous(
            entity_name="Alice Smith",
            score=0.72,
            candidate_id="ent-abc",
        )
    assert len(cap) == 1
    assert cap[0]["log_level"] == "info"
    assert cap[0]["event"] == "extraction.resolver_ambiguous"
    assert cap[0]["entity_name"] == "Alice Smith"
    assert cap[0]["score"] == 0.72
    assert cap[0]["candidate_id"] == "ent-abc"
