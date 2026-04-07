"""Atomic write logic: value normalization, claim supersession, workspace lock."""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

import structlog

from alayaos_core.extraction.resolver import normalize_name
from alayaos_core.repositories.claim import ClaimRepository
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.repositories.predicate import PredicateRepository
from alayaos_core.repositories.relation import RelationRepository

if TYPE_CHECKING:
    from alayaos_core.extraction.schemas import ExtractedClaim, ExtractionResult
    from alayaos_core.models.claim import L2Claim
    from alayaos_core.models.event import L0Event
    from alayaos_core.models.extraction_run import ExtractionRun

log = structlog.get_logger()


# ─── Task 1: Value normalization ─────────────────────────────────────────────


def normalize_claim_value(value: str, value_type: str, *, resolved_entity_id: str | None = None) -> dict:
    """Normalize claim value to JSONB format per spec."""
    if value_type == "text":
        return {"text": value}
    elif value_type == "date":
        iso = value if "T" in value else f"{value}T00:00:00Z"
        return {"date": value, "iso": iso}
    elif value_type == "number":
        try:
            num = float(value)
            return {"number": num, "raw": value}
        except ValueError:
            return {"text": value}  # fallback
    elif value_type == "boolean":
        return {"boolean": value.lower() in ("true", "1", "yes")}
    elif value_type == "entity_ref":
        result: dict = {"raw": value}
        if resolved_entity_id:
            result["entity_ref"] = resolved_entity_id
        return result
    return {"text": value}


# ─── Task 2: Claim supersession ──────────────────────────────────────────────


async def write_claim(
    claim: ExtractedClaim,
    entity_id: _uuid.UUID,
    event: L0Event,
    run: ExtractionRun,
    claim_repo: ClaimRepository,
    predicate_repo: PredicateRepository,
    entity_name_to_id: dict[str, _uuid.UUID],
) -> L2Claim | None:
    """Write a claim with predicate-specific supersession policy."""
    predicate_def = await predicate_repo.get_by_slug(event.workspace_id, claim.predicate)
    strategy = predicate_def.supersession_strategy if predicate_def else "latest_wins"
    claim_observed_at = event.occurred_at or event.created_at

    # Normalize value
    if claim.value_type == "entity_ref":
        ref_id = entity_name_to_id.get(normalize_name(claim.value))
        normalized_value = normalize_claim_value(
            claim.value, claim.value_type, resolved_entity_id=str(ref_id) if ref_id else None
        )
    else:
        normalized_value = normalize_claim_value(claim.value, claim.value_type)

    # accumulate: dedup by value
    if strategy == "accumulate":
        existing_values = await claim_repo.get_active_values_for_entity_predicate(entity_id, claim.predicate)
        if normalized_value in existing_values:
            return None

    # Create claim
    new_claim = await claim_repo.create(
        workspace_id=event.workspace_id,
        entity_id=entity_id,
        predicate=claim.predicate,
        predicate_id=predicate_def.id if predicate_def else None,
        value=normalized_value,
        value_type=claim.value_type,
        confidence=claim.confidence,
        observed_at=claim_observed_at,
        source_event_id=event.id,
        extraction_run_id=run.id,
        source_summary=claim.source_summary,
        status="active",
    )

    # Supersession (non-accumulate) — process ALL existing active claims
    if strategy != "accumulate":
        existing_claims = await claim_repo.get_active_for_entity_predicate(entity_id, claim.predicate)
        for old in existing_claims:
            if old.id == new_claim.id:
                continue
            old_observed = old.observed_at or old.created_at
            if strategy == "latest_wins":
                if claim_observed_at >= old_observed:
                    await claim_repo.mark_superseded(old.id, new_claim.id, claim_observed_at)
                else:
                    await claim_repo.mark_superseded(new_claim.id, old.id, old_observed)
                    break  # new claim superseded — stop processing
            elif strategy == "explicit_only":
                if claim.confidence >= 0.85 and normalized_value != old.value and claim_observed_at >= old_observed:
                    await claim_repo.mark_superseded(old.id, new_claim.id, claim_observed_at)
                elif normalized_value != old.value:
                    await claim_repo.update_status(new_claim.id, "disputed")
                    break  # new claim disputed — stop processing

    return new_claim


# ─── Task 3: Atomic write ────────────────────────────────────────────────────


async def atomic_write(
    extraction_result: ExtractionResult,
    event: L0Event,
    run: ExtractionRun,
    session,
    llm,
    entity_name_to_id: dict[str, _uuid.UUID] | None = None,
    resolver_decisions: list[dict] | None = None,
) -> dict:
    """Job 2: Atomic write — resolve entities, create relations+claims, update run."""
    from alayaos_core.extraction.resolver import resolve_batch

    entity_repo = EntityRepository(session)
    claim_repo = ClaimRepository(session)
    relation_repo = RelationRepository(session)
    predicate_repo = PredicateRepository(session)
    run_repo = ExtractionRunRepository(session)

    # Resolve entities if not already done
    if entity_name_to_id is None:
        entity_name_to_id, resolver_decisions = await resolve_batch(
            extraction_result.entities, event.workspace_id, run.id, session, llm, entity_repo
        )

    counters: dict[str, int] = {
        "entities_created": 0,
        "entities_merged": 0,
        "relations_created": 0,
        "claims_created": 0,
        "claims_superseded": 0,
    }

    # Count from resolver decisions
    for d in resolver_decisions or []:
        if d.get("is_new"):
            counters["entities_created"] += 1
        else:
            counters["entities_merged"] += 1

    # Write relations
    for rel in extraction_result.relations:
        src_id = entity_name_to_id.get(rel.source_entity)
        tgt_id = entity_name_to_id.get(rel.target_entity)
        if src_id and tgt_id:
            await relation_repo.create(
                workspace_id=event.workspace_id,
                source_entity_id=src_id,
                target_entity_id=tgt_id,
                relation_type=rel.relation_type,
                confidence=rel.confidence,
                extraction_run_id=run.id,
            )
            counters["relations_created"] += 1

    # Write claims
    for claim in extraction_result.claims:
        eid = entity_name_to_id.get(claim.entity)
        if eid:
            result = await write_claim(claim, eid, event, run, claim_repo, predicate_repo, entity_name_to_id)
            if result:
                counters["claims_created"] += 1

    # Update run counters
    await run_repo.update_counters(run.id, **counters)

    if resolver_decisions:
        run.resolver_decisions = resolver_decisions
        await session.flush()

    # Clear raw_extraction (no longer needed)
    await run_repo.clear_raw_extraction(run.id)

    # Mark event as extracted
    event.is_extracted = True
    await session.flush()

    return counters


# ─── Task 4: Workspace lock ──────────────────────────────────────────────────


async def acquire_workspace_lock(redis, workspace_id, timeout: int = 60) -> str | None:
    """Acquire lock with ownership token. Returns token or None."""
    token = str(_uuid.uuid4())
    key = f"extraction:write_lock:{workspace_id}"
    acquired = await redis.set(key, token, nx=True, ex=timeout)
    return token if acquired else None


async def release_workspace_lock(redis, workspace_id, token: str) -> bool:
    """Release lock only if we own it (Lua compare-and-delete)."""
    key = f"extraction:write_lock:{workspace_id}"
    script = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    return bool(await redis.eval(script, 1, key, token))
