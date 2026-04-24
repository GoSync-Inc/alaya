"""Repository for IntegratorAction — audit records for consolidator actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from alayaos_core.models.integrator_action import IntegratorAction
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.schemas.integrator_action import IntegratorActionCreate, IntegratorActionRollbackResponse


def _uuid_from_json(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _uuid_list_from_json(value: object) -> list[uuid.UUID]:
    if not isinstance(value, list):
        return []
    return [parsed for item in value if (parsed := _uuid_from_json(item)) is not None]


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


async def _rollback_merge(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Restore merge loser and reverse row movement for new merge audit payloads."""
    loser_id_str = action.inverse.get("loser_id")
    if not loser_id_str and action.targets:
        loser_id_str = action.targets[0] if isinstance(action.targets[0], str) else str(action.targets[0])

    if not loser_id_str:
        return []

    try:
        loser_id = uuid.UUID(loser_id_str)
    except ValueError:
        return []

    from alayaos_core.models.claim import L2Claim
    from alayaos_core.models.entity import L1Entity
    from alayaos_core.models.relation import L1Relation
    from alayaos_core.models.vector import VectorChunk

    stmt = select(L1Entity).where(L1Entity.id == loser_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    loser = result.scalar_one_or_none()

    winner = None
    winner_id = action.entity_id
    if winner_id is not None:
        winner_stmt = select(L1Entity).where(L1Entity.id == winner_id).where(L1Entity.workspace_id == action.workspace_id)
        winner_result = await repo.session.execute(winner_stmt)
        winner = winner_result.scalar_one_or_none()

    winner_snapshot = action.inverse.get("winner_snapshot")
    if not isinstance(winner_snapshot, dict):
        winner_snapshot = action.inverse
    if winner is not None:
        conflicts: list[str] = []
        expected_name = action.params.get("name")
        expected_desc = action.params.get("description")
        expected_aliases = action.params.get("aliases")
        if expected_name is not None and winner.name != expected_name:
            conflicts.append(f"name changed since action: expected '{expected_name}', found '{winner.name}'")
        if expected_desc is not None and winner.description != expected_desc:
            conflicts.append(f"description changed since action: expected '{expected_desc}', found '{winner.description}'")
        if isinstance(expected_aliases, list) and list(winner.aliases or []) != expected_aliases:
            conflicts.append("aliases changed since action")
        if conflicts and not force:
            return conflicts
        if "name" in winner_snapshot:
            winner.name = winner_snapshot["name"]
        if "description" in winner_snapshot:
            winner.description = winner_snapshot["description"]
        aliases = winner_snapshot.get("aliases")
        if isinstance(aliases, list):
            winner.aliases = aliases

    if loser is not None:
        loser.is_deleted = False
        loser_properties = action.inverse.get("loser_properties")
        if isinstance(loser_properties, dict):
            loser.properties = loser_properties
        else:
            restored_props = dict(loser.properties or {})
            restored_props.pop("merged_into", None)
            loser.properties = restored_props

    moved = action.inverse.get("moved")
    if not isinstance(moved, dict) or winner_id is None:
        return []

    claim_ids = _uuid_list_from_json(moved.get("claim_ids"))
    if claim_ids:
        await repo.session.execute(
            update(L2Claim)
            .where(L2Claim.workspace_id == action.workspace_id)
            .where(L2Claim.id.in_(claim_ids))
            .where(L2Claim.entity_id == winner_id)
            .values(entity_id=loser_id)
        )

    source_relation_ids = _uuid_list_from_json(moved.get("relation_source_ids"))
    if source_relation_ids:
        await repo.session.execute(
            update(L1Relation)
            .where(L1Relation.workspace_id == action.workspace_id)
            .where(L1Relation.id.in_(source_relation_ids))
            .where(L1Relation.source_entity_id == winner_id)
            .values(source_entity_id=loser_id)
        )

    target_relation_ids = _uuid_list_from_json(moved.get("relation_target_ids"))
    if target_relation_ids:
        await repo.session.execute(
            update(L1Relation)
            .where(L1Relation.workspace_id == action.workspace_id)
            .where(L1Relation.id.in_(target_relation_ids))
            .where(L1Relation.target_entity_id == winner_id)
            .values(target_entity_id=loser_id)
        )

    vector_chunk_ids = _uuid_list_from_json(moved.get("vector_chunk_ids"))
    if vector_chunk_ids:
        await repo.session.execute(
            update(VectorChunk)
            .where(VectorChunk.workspace_id == action.workspace_id)
            .where(VectorChunk.id.in_(vector_chunk_ids))
            .where(VectorChunk.source_type == "entity")
            .where(VectorChunk.source_id == winner_id)
            .values(source_id=loser_id)
        )

    deleted_relation_ids = set(_uuid_list_from_json(action.inverse.get("deleted_relation_ids")))
    relation_snapshots_raw = action.inverse.get("relation_snapshots")
    relation_snapshots: dict[uuid.UUID, dict] = {}
    if isinstance(relation_snapshots_raw, list):
        for snapshot in relation_snapshots_raw:
            if not isinstance(snapshot, dict):
                continue
            relation_id = _uuid_from_json(snapshot.get("id"))
            if relation_id is None:
                continue
            relation_snapshots[relation_id] = snapshot

    for relation_id in deleted_relation_ids:
        snapshot = relation_snapshots.get(relation_id)
        if snapshot is None:
            continue

        relation_stmt = (
            select(L1Relation)
            .where(L1Relation.id == relation_id)
            .where(L1Relation.workspace_id == action.workspace_id)
        )
        relation_result = await repo.session.execute(relation_stmt)
        existing_relation = relation_result.scalar_one_or_none()
        if existing_relation is not None:
            continue

        source_entity_id = _uuid_from_json(snapshot.get("source_entity_id"))
        target_entity_id = _uuid_from_json(snapshot.get("target_entity_id"))
        if source_entity_id is None or target_entity_id is None:
            continue

        created_at_raw = snapshot.get("created_at")
        updated_at_raw = snapshot.get("updated_at")
        created_at = datetime.fromisoformat(created_at_raw) if isinstance(created_at_raw, str) else datetime.now(UTC)
        updated_at = datetime.fromisoformat(updated_at_raw) if isinstance(updated_at_raw, str) else created_at

        repo.session.add(
            L1Relation(
                id=relation_id,
                workspace_id=action.workspace_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relation_type=snapshot.get("relation_type", ""),
                confidence=snapshot.get("confidence") or 1.0,
                relation_metadata=snapshot.get("metadata") or {},
                extraction_run_id=_uuid_from_json(snapshot.get("extraction_run_id")),
                created_at=created_at,
                updated_at=updated_at,
            )
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
