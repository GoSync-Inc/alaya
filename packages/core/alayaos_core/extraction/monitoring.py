"""Structlog event emitters for extraction anomaly monitoring."""

import structlog

log = structlog.get_logger()


def log_injection_detected(event_id: str, pattern: str, source_type: str) -> None:
    log.warning("extraction.injection_detected", event_id=event_id, pattern=pattern, source_type=source_type)


def log_high_entity_count(event_id: str, count: int, threshold: int = 50) -> None:
    if count > threshold:
        log.warning("extraction.high_entity_count", event_id=event_id, count=count, threshold=threshold)


def log_low_confidence_batch(run_id: str, avg_confidence: float, threshold: float = 0.6) -> None:
    if avg_confidence < threshold:
        log.warning("extraction.low_confidence_batch", run_id=run_id, avg_confidence=avg_confidence)


def log_resolver_ambiguous(entity_name: str, score: float, candidate_id: str) -> None:
    log.info("extraction.resolver_ambiguous", entity_name=entity_name, score=score, candidate_id=candidate_id)
