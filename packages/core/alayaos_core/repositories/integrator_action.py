"""Repository for IntegratorAction — audit records for consolidator actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from alayaos_core.models.integrator_action import IntegratorAction
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.schemas.integrator_action import IntegratorActionCreate, IntegratorActionRollbackResponse

log = structlog.get_logger(__name__)

# Fields that must be present in inverse for v2 rollback to be performed.
_V2_REQUIRED_INVERSE_FIELDS = (
    "moved_claim_ids",
    "moved_relation_source_ids",
    "moved_relation_target_ids",
    "moved_chunk_ids",
)


class IntegratorActionRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        data: IntegratorActionCreate,
    ) -> IntegratorAction:
        action = IntegratorAction(
            workspace_id=workspace_id,
            run_id=data.run_id,
            pass_number=data.pass_number,
            action_type=data.action_type,
            entity_id=data.entity_id,
            params=data.params,
            targets=data.targets,
            inverse=data.inverse,
            trace_id=data.trace_id,
            model_id=data.model_id,
            confidence=data.confidence,
            rationale=data.rationale,
            snapshot_schema_version=data.snapshot_schema_version,
            applied_at=datetime.now(UTC),
        )
        self.session.add(action)
        await self.session.flush()
        return await self.get_by_id(workspace_id, action.id)  # type: ignore[return-value]

    async def get_by_id(
        self,
        workspace_id: uuid.UUID,
        action_id: uuid.UUID,
    ) -> IntegratorAction | None:
        stmt = (
            select(IntegratorAction)
            .where(IntegratorAction.id == action_id)
            .where(IntegratorAction.workspace_id == workspace_id)
            .where(self._ws_filter(IntegratorAction))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_run(
        self,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[IntegratorAction], str | None, bool]:
        stmt = (
            select(IntegratorAction)
            .where(IntegratorAction.workspace_id == workspace_id)
            .where(IntegratorAction.run_id == run_id)
            .where(self._ws_filter(IntegratorAction))
        )
        stmt = self.apply_cursor_pagination(
            stmt,
            cursor,
            limit,
            IntegratorAction.created_at,
            IntegratorAction.id,
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def apply_rollback(
        self,
        workspace_id: uuid.UUID,
        action_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> IntegratorActionRollbackResponse | None:
        action = await self.get_by_id(workspace_id, action_id)
        if action is None:
            return None

        # Already rolled back — idempotent no-op
        if action.status == "rolled_back":
            return IntegratorActionRollbackResponse(
                reverted_action_id=action.id,
                conflicts=[],
            )

        handler = _ROLLBACK_HANDLERS.get(action.action_type)
        if handler is None:
            return IntegratorActionRollbackResponse(
                reverted_action_id=action.id,
                conflicts=[f"No rollback handler for action_type '{action.action_type}'"],
            )

        conflicts: list[str] = await handler(self, action, force=force)

        if not conflicts or force:
            action.status = "rolled_back"
            action.reverted_at = datetime.now(UTC)
            await self.session.flush()

        return IntegratorActionRollbackResponse(
            reverted_action_id=action.id,
            conflicts=conflicts if not force else [],
        )


# ─── Per-type rollback handlers ───────────────────────────────────────────────


async def _rollback_remove_noise(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Restore entity that was marked as noise (is_deleted → False)."""
    if action.entity_id is None:
        return []

    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == action.entity_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity is not None:
        entity.is_deleted = False
    return []


async def _rollback_reclassify(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Revert entity_type_id to old value from snapshot."""
    if action.entity_id is None:
        return []

    new_type_id_str = action.params.get("new_type_id")
    old_type_id_str = action.inverse.get("old_type_id")
    if not old_type_id_str:
        return []

    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == action.entity_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity is None:
        return []

    # Conflict detection: if entity_type_id is no longer what the action set, refuse
    if new_type_id_str is not None:
        try:
            expected_current = uuid.UUID(new_type_id_str)
        except ValueError:
            return []
        if entity.entity_type_id != expected_current and not force:
            return [f"entity_type changed since action: expected {expected_current}, found {entity.entity_type_id}"]

    try:
        old_type_id = uuid.UUID(old_type_id_str)
    except ValueError:
        return []

    entity.entity_type_id = old_type_id
    return []


async def _rollback_rewrite(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Revert entity name + description from inverse snapshot."""
    if action.entity_id is None:
        return []

    # Engine stores params as 'new_name'/'new_description'; legacy records may use 'name'/'description'
    new_name = action.params.get("new_name") or action.params.get("name")
    new_desc = action.params.get("new_description") or action.params.get("description")
    old_name = action.inverse.get("name")
    old_desc = action.inverse.get("description")

    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == action.entity_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity is None:
        return []

    conflicts: list[str] = []

    # Conflict detection: if name/desc differs from what action wrote, downstream edit
    if new_name is not None and entity.name != new_name:
        conflicts.append(f"name changed since action: expected '{new_name}', found '{entity.name}'")
    if new_desc is not None and entity.description != new_desc:
        conflicts.append(f"description changed since action: expected '{new_desc}', found '{entity.description}'")

    if conflicts and not force:
        return conflicts

    if old_name is not None:
        entity.name = old_name
    if old_desc is not None:
        entity.description = old_desc
    return []


# ─── Merge rollback helpers ────────────────────────────────────────────────────


async def _restore_loser(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    loser_id: uuid.UUID,
) -> None:
    """Set loser.is_deleted = False. Used by both legacy and v2 paths."""
    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == loser_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    loser = result.scalar_one_or_none()
    if loser is not None:
        loser.is_deleted = False


async def _check_merge_rollback_conflicts(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    loser_id: uuid.UUID,
    winner_id: uuid.UUID,
    *,
    force: bool,
) -> tuple[list[dict], dict[str, list[uuid.UUID]]]:
    """Per-ID state model conflict check.

    For each ID in moved_claim_ids + moved_relation_source_ids + moved_relation_target_ids
    + moved_chunk_ids, determines:
      - winner_id  → queue for reverse (add to reverse_plan)
      - loser_id   → already_restored (log + skip)
      - missing/soft-deleted → target_gone (log + skip)
      - other UUID → genuine conflict

    Returns (conflicts, reverse_plan).
    """
    from sqlalchemy import text

    inverse = action.inverse
    moved_claim_ids: list[str] = inverse.get("moved_claim_ids") or []
    moved_relation_source_ids: list[str] = inverse.get("moved_relation_source_ids") or []
    moved_relation_target_ids: list[str] = inverse.get("moved_relation_target_ids") or []
    moved_chunk_ids: list[str] = inverse.get("moved_chunk_ids") or []

    conflicts: list[dict] = []
    reverse_plan: dict[str, list[uuid.UUID]] = {
        "claim_ids": [],
        "relation_source_ids": [],
        "relation_target_ids": [],
        "chunk_ids": [],
    }

    ws_id = action.workspace_id

    # Check claims
    for claim_id_str in moved_claim_ids:
        try:
            claim_id = uuid.UUID(claim_id_str)
        except ValueError:
            continue
        result = await repo.session.execute(
            text("SELECT entity_id FROM l2_claims WHERE id = :id AND workspace_id = :ws_id"),
            {"id": claim_id, "ws_id": ws_id},
        )
        row = result.fetchone()
        if row is None:
            log.info("rollback_merge_target_gone", kind="claim", id=claim_id_str)
            continue
        current = uuid.UUID(str(row[0]))
        if current == winner_id:
            reverse_plan["claim_ids"].append(claim_id)
        elif current == loser_id:
            log.info("rollback_merge_already_restored", kind="claim", id=claim_id_str)
        else:
            conflicts.append({"id": claim_id_str, "current_holder": str(current), "expected_holder": str(winner_id)})

    # Check relations where loser was source
    for rel_id_str in moved_relation_source_ids:
        try:
            rel_id = uuid.UUID(rel_id_str)
        except ValueError:
            continue
        result = await repo.session.execute(
            text("SELECT source_entity_id FROM l1_relations WHERE id = :id AND workspace_id = :ws_id"),
            {"id": rel_id, "ws_id": ws_id},
        )
        row = result.fetchone()
        if row is None:
            log.info("rollback_merge_target_gone", kind="relation_source", id=rel_id_str)
            continue
        current = uuid.UUID(str(row[0]))
        if current == winner_id:
            reverse_plan["relation_source_ids"].append(rel_id)
        elif current == loser_id:
            log.info("rollback_merge_already_restored", kind="relation_source", id=rel_id_str)
        else:
            conflicts.append({"id": rel_id_str, "current_holder": str(current), "expected_holder": str(winner_id)})

    # Check relations where loser was target
    for rel_id_str in moved_relation_target_ids:
        try:
            rel_id = uuid.UUID(rel_id_str)
        except ValueError:
            continue
        result = await repo.session.execute(
            text("SELECT target_entity_id FROM l1_relations WHERE id = :id AND workspace_id = :ws_id"),
            {"id": rel_id, "ws_id": ws_id},
        )
        row = result.fetchone()
        if row is None:
            log.info("rollback_merge_target_gone", kind="relation_target", id=rel_id_str)
            continue
        current = uuid.UUID(str(row[0]))
        if current == winner_id:
            reverse_plan["relation_target_ids"].append(rel_id)
        elif current == loser_id:
            log.info("rollback_merge_already_restored", kind="relation_target", id=rel_id_str)
        else:
            conflicts.append({"id": rel_id_str, "current_holder": str(current), "expected_holder": str(winner_id)})

    # Check chunks
    for chunk_id_str in moved_chunk_ids:
        try:
            chunk_id = uuid.UUID(chunk_id_str)
        except ValueError:
            continue
        result = await repo.session.execute(
            text(
                "SELECT source_id FROM vector_chunks"
                " WHERE id = :id AND workspace_id = :ws_id AND source_type = 'entity'"
            ),
            {"id": chunk_id, "ws_id": ws_id},
        )
        row = result.fetchone()
        if row is None:
            log.info("rollback_merge_target_gone", kind="chunk", id=chunk_id_str)
            continue
        current = uuid.UUID(str(row[0]))
        if current == winner_id:
            reverse_plan["chunk_ids"].append(chunk_id)
        elif current == loser_id:
            log.info("rollback_merge_already_restored", kind="chunk", id=chunk_id_str)
        else:
            conflicts.append({"id": chunk_id_str, "current_holder": str(current), "expected_holder": str(winner_id)})

    return conflicts, reverse_plan


async def _reverse_merge_fks(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    loser_id: uuid.UUID,
    reverse_plan: dict[str, list[uuid.UUID]],
) -> None:
    """Execute bulk UPDATEs per reverse_plan to restore FKs back to loser_id."""
    from sqlalchemy import text

    ws_id = action.workspace_id

    if reverse_plan["claim_ids"]:
        ids = [str(i) for i in reverse_plan["claim_ids"]]
        await repo.session.execute(
            text("UPDATE l2_claims SET entity_id = :loser_id WHERE id = ANY(:ids) AND workspace_id = :ws_id"),
            {"loser_id": loser_id, "ids": ids, "ws_id": ws_id},
        )

    if reverse_plan["relation_source_ids"]:
        ids = [str(i) for i in reverse_plan["relation_source_ids"]]
        await repo.session.execute(
            text("UPDATE l1_relations SET source_entity_id = :loser_id WHERE id = ANY(:ids) AND workspace_id = :ws_id"),
            {"loser_id": loser_id, "ids": ids, "ws_id": ws_id},
        )

    if reverse_plan["relation_target_ids"]:
        ids = [str(i) for i in reverse_plan["relation_target_ids"]]
        await repo.session.execute(
            text("UPDATE l1_relations SET target_entity_id = :loser_id WHERE id = ANY(:ids) AND workspace_id = :ws_id"),
            {"loser_id": loser_id, "ids": ids, "ws_id": ws_id},
        )

    if reverse_plan["chunk_ids"]:
        ids = [str(i) for i in reverse_plan["chunk_ids"]]
        await repo.session.execute(
            text(
                "UPDATE vector_chunks SET source_id = :loser_id"
                " WHERE id = ANY(:ids) AND workspace_id = :ws_id AND source_type = 'entity'"
            ),
            {"loser_id": loser_id, "ids": ids, "ws_id": ws_id},
        )


async def _rollback_merge(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Full v2 merge rollback with FK reversal; degrades gracefully for v1 actions."""
    loser_id_str = action.inverse.get("loser_id")
    if not loser_id_str and action.targets:
        first = action.targets[0]
        loser_id_str = first if isinstance(first, str) else str(first)

    if not loser_id_str:
        return []

    try:
        loser_id = uuid.UUID(loser_id_str)
    except ValueError:
        return []

    # Determine if this action has full v2 inverse payload
    missing_fields = [f for f in _V2_REQUIRED_INVERSE_FIELDS if f not in action.inverse]
    is_v2 = action.snapshot_schema_version >= 2 and not missing_fields

    if not is_v2:
        # Legacy partial path: only restore loser entity
        reason = "version_lt_2" if action.snapshot_schema_version < 2 else "missing_fields"
        log.warning(
            "rollback_merge_legacy_partial",
            action_id=str(action.id),
            version=action.snapshot_schema_version,
            reason=reason,
            missing_fields=missing_fields,
        )
        await _restore_loser(repo, action, loser_id)
        return []

    # v2 path — determine winner_id from entity_id (the merge target)
    winner_id = action.entity_id
    if winner_id is None:
        log.warning(
            "rollback_merge_no_winner_id",
            action_id=str(action.id),
            loser_id=str(loser_id),
            reason="entity_id missing on v2 action — rolling back loser only",
        )
        # Fall back to legacy partial if no winner_id
        await _restore_loser(repo, action, loser_id)
        return []

    conflicts, reverse_plan = await _check_merge_rollback_conflicts(repo, action, loser_id, winner_id, force=force)

    if conflicts and not force:
        return [f"FK conflict for {c['id']}: holder={c['current_holder']}" for c in conflicts]

    # Execute FK reversal
    await _reverse_merge_fks(repo, action, loser_id, reverse_plan)

    # Restore winner metadata from inverse snapshot (v2 only)
    winner_before = action.inverse.get("winner_before")
    if winner_before and winner_id is not None:
        from alayaos_core.models.entity import L1Entity

        stmt = select(L1Entity).where(L1Entity.id == winner_id).where(L1Entity.workspace_id == action.workspace_id)
        result = await repo.session.execute(stmt)
        winner = result.scalar_one_or_none()
        if winner is not None:
            if "name" in winner_before:
                winner.name = winner_before["name"]
            if "description" in winner_before:
                winner.description = winner_before["description"]
            if "aliases" in winner_before:
                winner.aliases = winner_before["aliases"]
            log.info(
                "rollback_merge_winner_restored",
                loser_id=str(loser_id),
                winner_id=str(winner_id),
            )
        else:
            log.warning(
                "rollback_merge_winner_not_found",
                winner_id=str(winner_id),
            )

    # Restore the loser entity
    await _restore_loser(repo, action, loser_id)

    # Log skipped deleted relations (self-ref + dedup-duplicate)
    deleted_self_ref = action.inverse.get("deleted_self_ref_relation_ids") or []
    deduplicated = action.inverse.get("deduplicated_relation_ids") or []
    if deleted_self_ref or deduplicated:
        log.warning(
            "rollback_merge_skipped_deleted_relations",
            action_id=str(action.id),
            deleted_self_ref_relation_ids=deleted_self_ref,
            deduplicated_relation_ids=deduplicated,
        )

    return []


async def _rollback_create_from_cluster(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Soft-delete the synthetic entity created from cluster and delete its part_of relations."""
    if action.entity_id is None:
        return []

    from alayaos_core.models.entity import L1Entity
    from alayaos_core.models.relation import L1Relation

    stmt = select(L1Entity).where(L1Entity.id == action.entity_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity is not None:
        entity.is_deleted = True

    # Delete part_of relations stored as plain UUID strings in targets
    if action.targets:
        for target in action.targets:
            rel_id_str = target if isinstance(target, str) else None
            if not rel_id_str:
                continue
            try:
                rel_id = uuid.UUID(rel_id_str)
            except ValueError:
                continue
            rel_stmt = (
                select(L1Relation).where(L1Relation.id == rel_id).where(L1Relation.workspace_id == action.workspace_id)
            )
            rel_result = await repo.session.execute(rel_stmt)
            rel = rel_result.scalar_one_or_none()
            if rel is not None:
                repo.session.delete(rel)

    return []


async def _rollback_link_cross_type(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Delete the relation created by link_cross_type."""
    relation_id_str = action.params.get("relation_id")
    if not relation_id_str and action.targets:
        relation_id_str = action.targets[0] if isinstance(action.targets[0], str) else str(action.targets[0])

    if not relation_id_str:
        return []

    try:
        relation_id = uuid.UUID(relation_id_str)
    except ValueError:
        return []

    from alayaos_core.models.relation import L1Relation

    stmt = select(L1Relation).where(L1Relation.id == relation_id).where(L1Relation.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    rel = result.scalar_one_or_none()
    if rel is not None:
        repo.session.delete(rel)
    return []


_ROLLBACK_HANDLERS = {
    "remove_noise": _rollback_remove_noise,
    "reclassify": _rollback_reclassify,
    "rewrite": _rollback_rewrite,
    "merge": _rollback_merge,
    "create_from_cluster": _rollback_create_from_cluster,
    "link_cross_type": _rollback_link_cross_type,
}
