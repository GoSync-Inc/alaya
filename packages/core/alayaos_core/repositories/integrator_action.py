"""Repository for IntegratorAction — audit records for consolidator actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from alayaos_core.models.integrator_action import IntegratorAction
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.schemas.integrator_action import IntegratorActionCreate, IntegratorActionRollbackResponse


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

        conflicts: list[str] = []
        handler = _ROLLBACK_HANDLERS.get(action.action_type)
        if handler is not None:
            conflicts = await handler(self, action, force=force)

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

    new_name = action.params.get("name")
    new_desc = action.params.get("description")
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
    """Restore loser entity (is_deleted → False)."""
    loser_id_str = action.inverse.get("loser_id")
    if not loser_id_str and action.targets:
        loser_id_str = action.targets[0] if isinstance(action.targets[0], str) else str(action.targets[0])

    if not loser_id_str:
        return []

    try:
        loser_id = uuid.UUID(loser_id_str)
    except ValueError:
        return []

    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == loser_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    loser = result.scalar_one_or_none()
    if loser is not None:
        loser.is_deleted = False
    return []


async def _rollback_create_from_cluster(
    repo: IntegratorActionRepository,
    action: IntegratorAction,
    *,
    force: bool = False,
) -> list[str]:
    """Soft-delete the synthetic entity created from cluster."""
    if action.entity_id is None:
        return []

    from alayaos_core.models.entity import L1Entity

    stmt = select(L1Entity).where(L1Entity.id == action.entity_id).where(L1Entity.workspace_id == action.workspace_id)
    result = await repo.session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity is not None:
        entity.is_deleted = True
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
