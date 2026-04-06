import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from alayaos_core.models.entity import EntityExternalId, L1Entity
from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.repositories.base import BaseRepository


class EntityRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        entity_type_id: uuid.UUID,
        name: str,
        description: str | None = None,
        properties: dict | None = None,
    ) -> L1Entity:
        entity = L1Entity(
            workspace_id=workspace_id,
            entity_type_id=entity_type_id,
            name=name,
            description=description,
            properties=properties or {},
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_id(self, entity_id: uuid.UUID) -> L1Entity | None:
        stmt = (
            select(L1Entity)
            .where(L1Entity.id == entity_id)
            .options(selectinload(L1Entity.external_ids))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, entity_id: uuid.UUID, **kwargs) -> L1Entity | None:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None
        allowed = {"name", "description", "properties", "is_deleted"}
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
        stmt = select(L1Entity).where(L1Entity.is_deleted == False)  # noqa: E712
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
            .options(selectinload(L1Entity.external_ids))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
