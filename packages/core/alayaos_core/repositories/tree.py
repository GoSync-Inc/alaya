"""Repository for l3_tree_nodes table."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.tree import L3TreeNode
from alayaos_core.repositories.base import BaseRepository


class TreeNodeRepository(BaseRepository):
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        super().__init__(session, workspace_id)

    async def get_by_path(self, path: str) -> L3TreeNode | None:
        stmt = select(L3TreeNode).where(
            self._ws_filter(L3TreeNode),
            L3TreeNode.path == path,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_children(self, parent_path: str, depth: int = 1) -> list[L3TreeNode]:
        """Get direct children of a path."""
        prefix = parent_path.rstrip("/") + "/" if parent_path else ""

        stmt = (
            select(L3TreeNode)
            .where(
                self._ws_filter(L3TreeNode),
                L3TreeNode.path.like(f"{prefix}%"),
            )
            .order_by(L3TreeNode.sort_order, L3TreeNode.path)
        )

        result = await self.session.execute(stmt)
        nodes = list(result.scalars().all())

        # Filter to direct children only (depth=1)
        if depth == 1:
            nodes = [n for n in nodes if n.path.count("/") == prefix.count("/")]

        return nodes

    async def get_dirty_nodes(self) -> list[L3TreeNode]:
        stmt = select(L3TreeNode).where(
            self._ws_filter(L3TreeNode),
            L3TreeNode.is_dirty == True,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_node(
        self,
        workspace_id: uuid.UUID,
        path: str,
        node_type: str,
        entity_id: uuid.UUID | None = None,
    ) -> L3TreeNode:
        """Upsert a tree node. Creates if not exists, returns existing otherwise."""
        existing = await self.get_by_path(path)
        if existing:
            return existing

        node = L3TreeNode(
            workspace_id=workspace_id,
            path=path,
            node_type=node_type,
            entity_id=entity_id,
            is_dirty=True,
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def mark_dirty(self, entity_id: uuid.UUID) -> None:
        """Mark tree nodes associated with an entity as dirty."""
        stmt = (
            update(L3TreeNode)
            .where(
                self._ws_filter(L3TreeNode),
                L3TreeNode.entity_id == entity_id,
            )
            .values(is_dirty=True)
        )
        await self.session.execute(stmt)
