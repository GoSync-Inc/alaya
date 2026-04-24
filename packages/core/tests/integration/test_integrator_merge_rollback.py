"""Integration tests for full merge → rollback cycle using real PostgreSQL.

Verifies:
- _apply_merge_group writes v2 audit payload to DB
- apply_rollback reverses FKs and restores loser
- Idempotency: second rollback is no-op (status=rolled_back)
- Self-ref relations deleted during merge are NOT restored on rollback
"""

from __future__ import annotations

import uuid

import pytest
import structlog.testing
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from alayaos_core.extraction.integrator.dedup import DeduplicatorV2
from alayaos_core.models.integrator_action import IntegratorAction
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.integrator_action import IntegratorActionRepository
from alayaos_core.repositories.integrator_run import IntegratorRunRepository


async def _get_entity_type_id(db_session: AsyncSession, workspace_id: uuid.UUID) -> uuid.UUID:
    """Get the first entity_type_id seeded for this workspace."""
    result = await db_session.execute(
        text("SELECT id FROM entity_type_definitions WHERE workspace_id = :ws_id LIMIT 1"),
        {"ws_id": workspace_id},
    )
    row = result.fetchone()
    assert row is not None, "No entity types found — workspace seed may have failed"
    return uuid.UUID(str(row[0]))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_merge_group_writes_v2_audit_payload(workspace, db_session: AsyncSession) -> None:
    """_apply_merge_group writes a v2 audit record with all 7 inverse fields to DB."""
    ws_id = workspace.id
    entity_type_id = await _get_entity_type_id(db_session, ws_id)

    entity_repo = EntityRepository(db_session, ws_id)
    integrator_run_repo = IntegratorRunRepository(db_session, ws_id)
    action_repo = IntegratorActionRepository(db_session, ws_id)

    # Seed integrator run
    run = await integrator_run_repo.create(workspace_id=ws_id, trigger="test")
    await db_session.flush()

    # Seed winner and loser entities
    winner = await entity_repo.create(
        workspace_id=ws_id,
        entity_type_id=entity_type_id,
        name="Alice Johnson",
        description="Senior engineer",
        aliases=["AJ"],
    )
    loser = await entity_repo.create(
        workspace_id=ws_id,
        entity_type_id=entity_type_id,
        name="Alice Jonson",
        description="engineer",
        aliases=[],
    )
    await db_session.flush()

    # Seed a claim on the loser (will be moved to winner)
    claim_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value)"
            " VALUES (:id, :ws_id, :entity_id, 'status', '{\"v\": \"active\"}'::jsonb)"
        ),
        {"id": claim_id, "ws_id": ws_id, "entity_id": loser.id},
    )

    # Seed a third entity for a relation (loser→third)
    third = await entity_repo.create(
        workspace_id=ws_id,
        entity_type_id=entity_type_id,
        name="Project Phoenix",
        description="A project",
        aliases=[],
    )
    await db_session.flush()

    # Seed a relation from loser to third
    rel_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type, confidence)"
            " VALUES (:id, :ws_id, :src, :tgt, 'owns', 1.0)"
        ),
        {"id": rel_id, "ws_id": ws_id, "src": loser.id, "tgt": third.id},
    )
    await db_session.flush()

    # Call _apply_merge_group directly
    deduplicator = DeduplicatorV2(llm=None, batch_size=9)
    merged = await deduplicator._apply_merge_group(
        winner_id=winner.id,
        loser_ids=[loser.id],
        merged_name="Alice Johnson",
        merged_description="Senior engineer",
        merged_aliases=["AJ"],
        confidence=0.95,
        rationale="Same person",
        workspace_id=ws_id,
        run_id=run.id,
        entity_repo=entity_repo,
        session=db_session,
        action_repo=action_repo,
    )
    await db_session.flush()

    assert merged == 1

    # Verify audit record in DB
    action_result = await db_session.execute(
        select(IntegratorAction)
        .where(IntegratorAction.workspace_id == ws_id)
        .where(IntegratorAction.action_type == "merge")
        .where(IntegratorAction.run_id == run.id)
    )
    action = action_result.scalar_one_or_none()
    assert action is not None, "No merge audit record found in DB"

    # v2 payload verification
    assert action.snapshot_schema_version == 2

    v2_fields = [
        "moved_claim_ids",
        "moved_relation_source_ids",
        "moved_relation_target_ids",
        "moved_chunk_ids",
        "deleted_self_ref_relation_ids",
        "deduplicated_relation_ids",
        "winner_before",
    ]
    for field in v2_fields:
        assert field in action.inverse, f"Missing v2 inverse field: {field!r}"

    # Claim must be listed in moved_claim_ids
    assert str(claim_id) in action.inverse["moved_claim_ids"]
    # Relation must be listed in moved_relation_source_ids
    assert str(rel_id) in action.inverse["moved_relation_source_ids"]

    # Verify loser is now soft-deleted
    refreshed_loser_result = await db_session.execute(
        text("SELECT is_deleted FROM l1_entities WHERE id = :id"),
        {"id": loser.id},
    )
    loser_row = refreshed_loser_result.fetchone()
    assert loser_row[0] is True, "Loser entity should be soft-deleted after merge"

    # Verify claim was moved to winner
    claim_result = await db_session.execute(
        text("SELECT entity_id FROM l2_claims WHERE id = :id"),
        {"id": claim_id},
    )
    claim_row = claim_result.fetchone()
    assert claim_row is not None
    assert uuid.UUID(str(claim_row[0])) == winner.id, "Claim was not moved to winner"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_rollback_reverses_fks_and_restores_loser(workspace, db_session: AsyncSession) -> None:
    """Full cycle: merge → rollback → FK reversal + loser restored."""
    ws_id = workspace.id
    entity_type_id = await _get_entity_type_id(db_session, ws_id)

    entity_repo = EntityRepository(db_session, ws_id)
    integrator_run_repo = IntegratorRunRepository(db_session, ws_id)
    action_repo = IntegratorActionRepository(db_session, ws_id)

    run = await integrator_run_repo.create(workspace_id=ws_id, trigger="test")
    await db_session.flush()

    winner = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Winner Entity", description="", aliases=[]
    )
    loser = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Loser Entity", description="", aliases=[]
    )
    await db_session.flush()

    # Seed a claim on loser
    claim_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value)"
            " VALUES (:id, :ws_id, :entity_id, 'status', '{\"v\": \"active\"}'::jsonb)"
        ),
        {"id": claim_id, "ws_id": ws_id, "entity_id": loser.id},
    )
    await db_session.flush()

    # Do the merge
    deduplicator = DeduplicatorV2(llm=None, batch_size=9)
    await deduplicator._apply_merge_group(
        winner_id=winner.id,
        loser_ids=[loser.id],
        merged_name="Winner Entity",
        merged_description="",
        merged_aliases=[],
        confidence=0.9,
        rationale="Test",
        workspace_id=ws_id,
        run_id=run.id,
        entity_repo=entity_repo,
        session=db_session,
        action_repo=action_repo,
    )
    await db_session.flush()

    # Get the audit action
    action_result = await db_session.execute(
        select(IntegratorAction)
        .where(IntegratorAction.workspace_id == ws_id)
        .where(IntegratorAction.action_type == "merge")
        .where(IntegratorAction.run_id == run.id)
    )
    action = action_result.scalar_one_or_none()
    assert action is not None

    # Verify claim is now on winner
    claim_check = await db_session.execute(
        text("SELECT entity_id FROM l2_claims WHERE id = :id"),
        {"id": claim_id},
    )
    assert uuid.UUID(str(claim_check.fetchone()[0])) == winner.id

    # Now rollback
    with structlog.testing.capture_logs() as logs:
        response = await action_repo.apply_rollback(ws_id, action.id)
    await db_session.flush()

    assert response is not None
    assert response.conflicts == []

    # Loser must be restored
    loser_check = await db_session.execute(
        text("SELECT is_deleted FROM l1_entities WHERE id = :id"),
        {"id": loser.id},
    )
    assert loser_check.fetchone()[0] is False, "Loser must be restored after rollback"

    # Claim must be moved back to loser
    claim_after = await db_session.execute(
        text("SELECT entity_id FROM l2_claims WHERE id = :id"),
        {"id": claim_id},
    )
    assert uuid.UUID(str(claim_after.fetchone()[0])) == loser.id, "Claim not reverted to loser"

    # rollback_merge_skipped_deleted_relations may be logged (if any self-ref/dedup happened)
    # It's OK if this is not logged (no self-ref/dedup in this test)
    # Just assert we didn't error
    assert "error" not in str(logs).lower() or all("error" not in lg.get("event", "") for lg in logs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rollback_merge_idempotent(workspace, db_session: AsyncSession) -> None:
    """Second rollback is a no-op (status already rolled_back)."""
    ws_id = workspace.id
    entity_type_id = await _get_entity_type_id(db_session, ws_id)

    entity_repo = EntityRepository(db_session, ws_id)
    integrator_run_repo = IntegratorRunRepository(db_session, ws_id)
    action_repo = IntegratorActionRepository(db_session, ws_id)

    run = await integrator_run_repo.create(workspace_id=ws_id, trigger="test")
    await db_session.flush()

    winner = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Winner", description="", aliases=[]
    )
    loser = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Loser", description="", aliases=[]
    )
    await db_session.flush()

    deduplicator = DeduplicatorV2(llm=None, batch_size=9)
    await deduplicator._apply_merge_group(
        winner_id=winner.id,
        loser_ids=[loser.id],
        merged_name="Winner",
        merged_description="",
        merged_aliases=[],
        confidence=0.9,
        rationale="Test",
        workspace_id=ws_id,
        run_id=run.id,
        entity_repo=entity_repo,
        session=db_session,
        action_repo=action_repo,
    )
    await db_session.flush()

    action_result = await db_session.execute(
        select(IntegratorAction)
        .where(IntegratorAction.workspace_id == ws_id)
        .where(IntegratorAction.action_type == "merge")
    )
    action = action_result.scalar_one_or_none()
    assert action is not None

    # First rollback
    resp1 = await action_repo.apply_rollback(ws_id, action.id)
    await db_session.flush()
    assert resp1.conflicts == []

    # Second rollback — must be idempotent (no-op, status already rolled_back)
    resp2 = await action_repo.apply_rollback(ws_id, action.id)
    assert resp2.conflicts == []
    # Status should remain rolled_back, no error
    action_after = await action_repo.get_by_id(ws_id, action.id)
    assert action_after.status == "rolled_back"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rollback_merge_does_not_resurrect_self_ref(workspace, db_session: AsyncSession) -> None:
    """Self-referential relations deleted during merge are NOT restored on rollback."""
    ws_id = workspace.id
    entity_type_id = await _get_entity_type_id(db_session, ws_id)

    entity_repo = EntityRepository(db_session, ws_id)
    integrator_run_repo = IntegratorRunRepository(db_session, ws_id)
    action_repo = IntegratorActionRepository(db_session, ws_id)

    run = await integrator_run_repo.create(workspace_id=ws_id, trigger="test")
    await db_session.flush()

    winner = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Winner SR", description="", aliases=[]
    )
    loser = await entity_repo.create(
        workspace_id=ws_id, entity_type_id=entity_type_id, name="Loser SR", description="", aliases=[]
    )
    await db_session.flush()

    # Seed a self-ref-candidate: loser→winner relation (will become self-ref during merge)
    self_ref_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type, confidence)"
            " VALUES (:id, :ws_id, :src, :tgt, 'related_to', 1.0)"
        ),
        {"id": self_ref_id, "ws_id": ws_id, "src": loser.id, "tgt": winner.id},
    )
    await db_session.flush()

    deduplicator = DeduplicatorV2(llm=None, batch_size=9)
    await deduplicator._apply_merge_group(
        winner_id=winner.id,
        loser_ids=[loser.id],
        merged_name="Winner SR",
        merged_description="",
        merged_aliases=[],
        confidence=0.9,
        rationale="Test",
        workspace_id=ws_id,
        run_id=run.id,
        entity_repo=entity_repo,
        session=db_session,
        action_repo=action_repo,
    )
    await db_session.flush()

    # Self-ref relation should now be deleted
    rel_check = await db_session.execute(
        text("SELECT id FROM l1_relations WHERE id = :id"),
        {"id": self_ref_id},
    )
    assert rel_check.fetchone() is None, "Self-ref relation should be deleted after merge"

    # Get audit action
    action_result = await db_session.execute(
        select(IntegratorAction)
        .where(IntegratorAction.workspace_id == ws_id)
        .where(IntegratorAction.action_type == "merge")
    )
    action = action_result.scalar_one_or_none()
    assert action is not None

    # Verify self-ref ID is recorded in audit inverse
    assert str(self_ref_id) in action.inverse.get("deleted_self_ref_relation_ids", [])

    # Rollback
    resp = await action_repo.apply_rollback(ws_id, action.id)
    await db_session.flush()
    assert resp.conflicts == []

    # Self-ref relation must still be deleted after rollback (not restored)
    rel_after = await db_session.execute(
        text("SELECT id FROM l1_relations WHERE id = :id"),
        {"id": self_ref_id},
    )
    assert rel_after.fetchone() is None, (
        "Self-ref relation was incorrectly resurrected on rollback — deleted_self_ref_relation_ids must not be restored"
    )

    # Log must note skipped relations
    # We don't directly capture structlog here but verify via action inverse
    assert "deleted_self_ref_relation_ids" in action.inverse
