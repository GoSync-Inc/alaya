import uuid

from sqlalchemy import select

from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.repositories.base import BaseRepository


class EntityTypeRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        slug: str,
        display_name: str,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        is_core: bool = False,
    ) -> EntityTypeDefinition:
        et = EntityTypeDefinition(
            workspace_id=workspace_id,
            slug=slug,
            display_name=display_name,
            description=description,
            icon=icon,
            color=color,
            is_core=is_core,
        )
        self.session.add(et)
        await self.session.flush()
        return et

    async def get_by_id(self, type_id: uuid.UUID) -> EntityTypeDefinition | None:
        stmt = (
            select(EntityTypeDefinition)
            .where(EntityTypeDefinition.id == type_id)
            .where(self._ws_filter(EntityTypeDefinition))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, workspace_id: uuid.UUID, slug: str) -> EntityTypeDefinition | None:
        stmt = (
            select(EntityTypeDefinition)
            .where(
                EntityTypeDefinition.workspace_id == workspace_id,
                EntityTypeDefinition.slug == slug,
            )
            .where(self._ws_filter(EntityTypeDefinition))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[EntityTypeDefinition], str | None, bool]:
        stmt = select(EntityTypeDefinition).where(self._ws_filter(EntityTypeDefinition))
        stmt = self.apply_cursor_pagination(
            stmt, cursor, limit, EntityTypeDefinition.created_at, EntityTypeDefinition.id
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def upsert_core(
        self,
        workspace_id: uuid.UUID,
        slug: str,
        display_name: str,
        description: str | None = None,
    ) -> EntityTypeDefinition:
        """Create if not exists; do NOT overwrite user-customized non-core types."""
        existing = await self.get_by_slug(workspace_id, slug)
        if existing is not None:
            return existing
        return await self.create(
            workspace_id=workspace_id,
            slug=slug,
            display_name=display_name,
            description=description,
            is_core=True,
        )
