import uuid

from sqlalchemy import select

from alayaos_core.models.predicate import PredicateDefinition
from alayaos_core.repositories.base import BaseRepository


class PredicateRepository(BaseRepository):
    async def get_by_id(self, predicate_id: uuid.UUID) -> PredicateDefinition | None:
        stmt = (
            select(PredicateDefinition)
            .where(PredicateDefinition.id == predicate_id)
            .where(self._ws_filter(PredicateDefinition))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, workspace_id: uuid.UUID, slug: str) -> PredicateDefinition | None:
        stmt = (
            select(PredicateDefinition)
            .where(
                PredicateDefinition.workspace_id == workspace_id,
                PredicateDefinition.slug == slug,
            )
            .where(self._ws_filter(PredicateDefinition))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[PredicateDefinition], str | None, bool]:
        stmt = select(PredicateDefinition).where(self._ws_filter(PredicateDefinition))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, PredicateDefinition.created_at, PredicateDefinition.id)
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
        value_type: str = "text",
        description: str | None = None,
        inverse_slug: str | None = None,
        is_core: bool = True,
        supersession_strategy: str = "latest_wins",
    ) -> PredicateDefinition:
        """Create if not exists; update supersession_strategy on existing core predicates."""
        existing = await self.get_by_slug(workspace_id, slug)
        if existing is not None:
            if is_core and existing.supersession_strategy != supersession_strategy:
                existing.supersession_strategy = supersession_strategy
            return existing
        pred = PredicateDefinition(
            workspace_id=workspace_id,
            slug=slug,
            display_name=display_name,
            value_type=value_type,
            description=description,
            inverse_slug=inverse_slug,
            is_core=is_core,
            supersession_strategy=supersession_strategy,
        )
        self.session.add(pred)
        await self.session.flush()
        return pred
