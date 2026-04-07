import uuid

from sqlalchemy import select

from alayaos_core.models.event import L0Event
from alayaos_core.repositories.base import BaseRepository


class EventRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        source_type: str,
        source_id: str,
        content: dict,
        content_hash: str | None = None,
        metadata: dict | None = None,
    ) -> L0Event:
        event = L0Event(
            workspace_id=workspace_id,
            source_type=source_type,
            source_id=source_id,
            content=content,
            content_hash=content_hash,
            event_metadata=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def create_or_update(
        self,
        workspace_id: uuid.UUID,
        source_type: str,
        source_id: str,
        content: dict,
        content_hash: str | None = None,
        metadata: dict | None = None,
    ) -> tuple[L0Event, bool]:
        """Idempotent upsert by (workspace_id, source_type, source_id).

        Returns (event, created). If content_hash changed -> update; if identical -> skip.
        """
        stmt = select(L0Event).where(
            L0Event.workspace_id == workspace_id,
            L0Event.source_type == source_type,
            L0Event.source_id == source_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            event = await self.create(
                workspace_id=workspace_id,
                source_type=source_type,
                source_id=source_id,
                content=content,
                content_hash=content_hash,
                metadata=metadata,
            )
            return event, True

        # If content_hash is the same (and both are non-None), skip update
        if content_hash is not None and existing.content_hash == content_hash:
            return existing, False

        existing.content = content
        existing.content_hash = content_hash
        if metadata is not None:
            existing.event_metadata = metadata
        await self.session.flush()
        return existing, False

    async def get_by_id(self, event_id: uuid.UUID) -> L0Event | None:
        stmt = select(L0Event).where(L0Event.id == event_id).where(self._ws_filter(L0Event))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[L0Event], str | None, bool]:
        stmt = select(L0Event).where(self._ws_filter(L0Event))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L0Event.created_at, L0Event.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more
