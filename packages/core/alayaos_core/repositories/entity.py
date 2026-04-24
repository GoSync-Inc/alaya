from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, column, func, not_, or_, select, table, text
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from alayaos_core.models.claim import L2Claim
from alayaos_core.models.entity import EntityExternalId, L1Entity
from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.repositories.base import BaseRepository

_CLAIM_EFFECTIVE_ACCESS = table(
    "claim_effective_access",
    column("workspace_id"),
    column("claim_id"),
    column("max_tier_rank"),
)
_CALLER_MAX_TIER_RANK = text("(SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x)")
_CALLER_CAN_SEE_RESTRICTED = text("3 <= (SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x)")


class EntityRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        entity_type_id: uuid.UUID,
        name: str,
        description: str | None = None,
        properties: dict | None = None,
        aliases: list[str] | None = None,
        extraction_run_id: uuid.UUID | None = None,
    ) -> L1Entity:
        entity = L1Entity(
            workspace_id=workspace_id,
            entity_type_id=entity_type_id,
            name=name,
            description=description,
            properties=properties or {},
            aliases=aliases or [],
            extraction_run_id=extraction_run_id,
        )
        self.session.add(entity)
        await self.session.flush()
        set_committed_value(entity, "external_ids", [])
        return entity

    async def get_by_id(self, entity_id: uuid.UUID) -> L1Entity | None:
        visible_filter = self._visible_entity_filter()
        stmt = (
            select(L1Entity)
            .where(L1Entity.id == entity_id)
            .where(self._ws_filter(L1Entity))
            .where(visible_filter)
            .options(selectinload(L1Entity.external_ids))
        )
        result = await self.session.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is not None and not await self._caller_is_admin() and await self._entity_has_claims(entity.id):
            self._mask_acl_safe_fields([entity])
        return entity

    async def get_by_id_unfiltered(self, entity_id: uuid.UUID) -> L1Entity | None:
        """Internal lookup that bypasses claim visibility ACL while preserving workspace scope."""
        stmt = (
            select(L1Entity)
            .where(L1Entity.id == entity_id)
            .where(self._ws_filter(L1Entity))
            .options(selectinload(L1Entity.external_ids))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, entity_id: uuid.UUID, **kwargs) -> L1Entity | None:
        entity = await self.get_by_id(entity_id)
        updated = await self._update_entity(entity, **kwargs)
        if updated is None:
            return None
        # Re-fetch to get server-updated fields (updated_at) and eager-loaded relationships
        return await self.get_by_id(entity_id)

    async def update_unfiltered(self, entity_id: uuid.UUID, **kwargs) -> L1Entity | None:
        entity = await self.get_by_id_unfiltered(entity_id)
        updated = await self._update_entity(entity, **kwargs)
        if updated is None:
            return None
        # Re-fetch to get server-updated fields (updated_at) and eager-loaded relationships
        return await self.get_by_id_unfiltered(entity_id)

    async def _update_entity(self, entity: L1Entity | None, **kwargs) -> L1Entity | None:
        if entity is None:
            return None
        allowed = {"name", "description", "properties", "aliases", "is_deleted"}
        for key, value in kwargs.items():
            if key in allowed:
                setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
        type_slug: str | None = None,
    ) -> tuple[list[L1Entity], str | None, bool]:
        visible_filter = self._visible_entity_filter()
        base_stmt = (
            select(L1Entity)
            .where(L1Entity.is_deleted == False)  # noqa: E712
            .where(self._ws_filter(L1Entity))
        )
        if type_slug is not None:
            base_stmt = base_stmt.join(EntityTypeDefinition, L1Entity.entity_type_id == EntityTypeDefinition.id).where(
                EntityTypeDefinition.slug == type_slug
            )
        visible_stmt = base_stmt.where(visible_filter)
        self.last_filtered_count = await self._filtered_count(base_stmt, visible_stmt)
        stmt = visible_stmt.options(selectinload(L1Entity.external_ids))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L1Entity.created_at, L1Entity.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        if not await self._caller_is_admin():
            claimed_ids = await self._entity_ids_with_claims([item.id for item in items])
            self._mask_acl_safe_fields([item for item in items if item.id in claimed_ids])
        return items, next_cursor, has_more

    async def list_unfiltered(
        self,
        cursor: str | None = None,
        limit: int = 50,
        type_slug: str | None = None,
    ) -> tuple[list[L1Entity], str | None, bool]:
        """Internal list that bypasses claim visibility ACL while preserving workspace scope."""
        stmt = (
            select(L1Entity)
            .where(L1Entity.is_deleted == False)  # noqa: E712
            .where(self._ws_filter(L1Entity))
            .options(selectinload(L1Entity.external_ids))
        )
        if type_slug is not None:
            stmt = stmt.join(EntityTypeDefinition, L1Entity.entity_type_id == EntityTypeDefinition.id).where(
                EntityTypeDefinition.slug == type_slug
            )
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L1Entity.created_at, L1Entity.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def _caller_is_admin(self) -> bool:
        result = await self.session.execute(text("SELECT 'restricted' = ANY(alaya_current_allowed_access())"))
        return bool(result.scalar())

    @staticmethod
    def _mask_acl_safe_fields(entities: list[L1Entity]) -> None:
        for entity in entities:
            set_committed_value(entity, "description", None)
            set_committed_value(entity, "properties", {})

    def _visible_active_claim_exists(self):
        return (
            select(1)
            .select_from(L2Claim)
            .join(
                _CLAIM_EFFECTIVE_ACCESS,
                and_(
                    _CLAIM_EFFECTIVE_ACCESS.c.claim_id == L2Claim.id,
                    _CLAIM_EFFECTIVE_ACCESS.c.workspace_id == L2Claim.workspace_id,
                ),
            )
            .where(L2Claim.entity_id == L1Entity.id)
            .where(L2Claim.workspace_id == L1Entity.workspace_id)
            .where(L2Claim.status == "active")
            .where(_CLAIM_EFFECTIVE_ACCESS.c.max_tier_rank <= _CALLER_MAX_TIER_RANK)
            .exists()
        )

    def _claim_exists(self):
        return (
            select(1)
            .select_from(L2Claim)
            .where(L2Claim.entity_id == L1Entity.id)
            .where(L2Claim.workspace_id == L1Entity.workspace_id)
            .exists()
        )

    def _visible_entity_filter(self):
        return or_(_CALLER_CAN_SEE_RESTRICTED, self._visible_active_claim_exists(), not_(self._claim_exists()))

    async def _entity_has_claims(self, entity_id: uuid.UUID) -> bool:
        result = await self.session.scalar(
            select(L2Claim.id).where(L2Claim.entity_id == entity_id).where(self._ws_filter(L2Claim)).limit(1)
        )
        return result is not None

    async def _entity_ids_with_claims(self, entity_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not entity_ids:
            return set()
        result = await self.session.execute(
            select(L2Claim.entity_id).where(L2Claim.entity_id.in_(entity_ids)).where(self._ws_filter(L2Claim))
        )
        return set(result.scalars().all())

    async def _filtered_count(self, base_stmt, visible_stmt) -> int:
        total = await self.session.scalar(select(func.count()).select_from(base_stmt.subquery()))
        visible = await self.session.scalar(select(func.count()).select_from(visible_stmt.subquery()))
        return max(int(total or 0) - int(visible or 0), 0)

    async def create_external_id(
        self,
        workspace_id: uuid.UUID,
        entity_id: uuid.UUID,
        source_type: str,
        external_id: str,
    ) -> EntityExternalId:
        ext = EntityExternalId(
            workspace_id=workspace_id,
            entity_id=entity_id,
            source_type=source_type,
            external_id=external_id,
        )
        self.session.add(ext)
        await self.session.flush()
        return ext

    async def list_recent(
        self,
        workspace_id: uuid.UUID,
        hours: int = 48,
        limit: int = 500,
    ) -> list[L1Entity]:
        """List entities updated within the last N hours."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(L1Entity)
            .where(L1Entity.workspace_id == workspace_id)
            .where(L1Entity.updated_at >= cutoff)
            .where(self._ws_filter(L1Entity))
            .options(selectinload(L1Entity.external_ids))
            .order_by(L1Entity.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_external_id(
        self,
        workspace_id: uuid.UUID,
        source_type: str,
        external_id: str,
    ) -> L1Entity | None:
        stmt = (
            select(L1Entity)
            .join(EntityExternalId, L1Entity.id == EntityExternalId.entity_id)
            .where(
                EntityExternalId.workspace_id == workspace_id,
                EntityExternalId.source_type == source_type,
                EntityExternalId.external_id == external_id,
            )
            .where(self._ws_filter(L1Entity))
            .options(selectinload(L1Entity.external_ids))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
