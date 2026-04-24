import uuid
from datetime import datetime

from sqlalchemy import any_, func, literal_column, select
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
        raw_text: str | None = None,
        access_level: str = "public",
        event_kind: str | None = None,
        occurred_at: datetime | None = None,
    ) -> tuple[L0Event, bool]:
        """Atomic upsert by (workspace_id, source_type, source_id).

        Returns (event, created). Uses INSERT ON CONFLICT for atomicity.
        """
        values: dict = {
            "workspace_id": workspace_id,
            "source_type": source_type,
            "source_id": source_id,
            "content": content,
            "content_hash": content_hash,
            "event_metadata": metadata or {},
            "raw_text": raw_text,
            "access_level": access_level,
            "event_kind": event_kind,
            "occurred_at": occurred_at,
        }
        stmt = pg_insert(L0Event).values(**values)
        update_set: dict = {
            "content": stmt.excluded.content,
            "content_hash": stmt.excluded.content_hash,
            "raw_text": stmt.excluded.raw_text,
            "access_level": stmt.excluded.access_level,
            "event_kind": stmt.excluded.event_kind,
            "occurred_at": stmt.excluded.occurred_at,
            "updated_at": func.now(),
        }
        if metadata is not None:
            update_set["metadata"] = stmt.excluded["metadata"]

        stmt = stmt.on_conflict_do_update(
            constraint="uq_l0_events_ws_src",
            set_=update_set,
        )
        stmt = stmt.returning(L0Event, literal_column("xmax = 0").label("inserted"))
        result = await self.session.execute(stmt)
        row = result.one()
        return row[0], bool(row[1])

    async def get_by_id(self, event_id: uuid.UUID) -> L0Event | None:
        stmt = (
            select(L0Event)
            .where(L0Event.id == event_id)
            .where(self._ws_filter(L0Event))
            .where(L0Event.access_level == any_(func.alaya_current_allowed_access()))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_unfiltered(self, event_id: uuid.UUID) -> L0Event | None:
        """Internal lookup that bypasses retrieval ACL while preserving workspace scope."""
        stmt = select(L0Event).where(L0Event.id == event_id).where(self._ws_filter(L0Event))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[L0Event], str | None, bool]:
        base_stmt = select(L0Event).where(self._ws_filter(L0Event))
        visible_stmt = base_stmt.where(L0Event.access_level == any_(func.alaya_current_allowed_access()))
        self.last_filtered_count = await self._filtered_count(base_stmt, visible_stmt)
        stmt = visible_stmt
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L0Event.created_at, L0Event.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def _filtered_count(self, base_stmt, visible_stmt) -> int:
        total = await self.session.scalar(select(func.count()).select_from(base_stmt.subquery()))
        visible = await self.session.scalar(select(func.count()).select_from(visible_stmt.subquery()))
        return max(int(total or 0) - int(visible or 0), 0)
