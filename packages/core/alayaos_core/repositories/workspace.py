import uuid

from sqlalchemy import select

from alayaos_core.models.workspace import Workspace
from alayaos_core.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository):
    async def create(
        self,
        name: str,
        slug: str,
        settings: dict | None = None,
    ) -> Workspace:
        workspace = Workspace(
            name=name,
            slug=slug,
            settings=settings or {},
        )
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, workspace_id: uuid.UUID) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        result = self.session.execute(stmt)
        if hasattr(result, "__await__"):
            result = await result
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, workspace_id: uuid.UUID, **kwargs) -> Workspace | None:
        workspace = await self.get_by_id(workspace_id)
        if workspace is None:
            return None
        allowed = {"name", "slug", "settings"}
        for key, value in kwargs.items():
            if key in allowed:
                setattr(workspace, key, value)
        await self.session.flush()
        return await self.get_by_id(workspace_id)

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Workspace], str | None, bool]:
        stmt = select(Workspace)
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, Workspace.created_at, Workspace.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more
