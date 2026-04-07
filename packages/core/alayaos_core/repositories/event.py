import uuid

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
        """Atomic upsert by (workspace_id, source_type, source_id).

        Returns (event, created). Uses INSERT ON CONFLICT for atomicity.
        """
        values = {
            "workspace_id": workspace_id,
            "source_type": source_type,
            "source_id": source_id,
            "content": content,
            "content_hash": content_hash,
            "event_metadata": metadata or {},
        }
        stmt = pg_insert(L0Event).values(**values)
        update_set: dict = {
            "content": stmt.excluded.content,
            "content_hash": stmt.excluded.content_hash,
            "updated_at": func.now(),
        }
        if metadata is not None:
            update_set["event_metadata"] = stmt.excluded.event_metadata

        stmt = stmt.on_conflict_do_update(
            constraint="uq_l0_events_ws_src",
            set_=update_set,
        )
        stmt = stmt.returning(L0Event, literal_column("xmax = 0").label("inserted"))
        result = await self.session.execute(stmt)
        row = result.one()
        return row[0], bool(row[1])

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
