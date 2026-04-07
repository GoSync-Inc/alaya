"""Structlog event emitters for extraction anomaly monitoring."""

import structlog

log = structlog.get_logger()


def log_injection_detected(event_id: str, pattern: str, text_preview: str) -> None:
    log.warning("injection_detected", event_id=event_id, pattern=pattern, text_preview=text_preview[:100])


def log_high_entity_count(event_id: str, count: int, threshold: int = 50) -> None:
    if count > threshold:
        log.warning("high_entity_count", event_id=event_id, count=count, threshold=threshold)


def log_low_confidence_batch(run_id: str, avg_confidence: float, threshold: float = 0.5) -> None:
    if avg_confidence < threshold:
        log.warning("low_confidence_batch", run_id=run_id, avg_confidence=avg_confidence)


def log_restricted_skipped(event_id: str, access_level: str) -> None:
    log.info("restricted_skipped", event_id=event_id, access_level=access_level)


def log_resolver_ambiguous(entity_name: str, score: float, candidate_id: str) -> None:
    log.info("resolver_ambiguous", entity_name=entity_name, score=score, candidate_id=candidate_id)
