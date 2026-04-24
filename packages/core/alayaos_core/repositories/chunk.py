"""Repository for L0Chunk — chunked events for the Cortex pipeline."""

from __future__ import annotations

import uuid

from sqlalchemy import any_, func, select

from alayaos_core.models.chunk import L0Chunk
from alayaos_core.models.event import L0Event
from alayaos_core.repositories.base import BaseRepository


class ChunkRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        event_id: uuid.UUID,
        chunk_index: int,
        chunk_total: int,
        text: str,
        token_count: int,
        source_type: str,
        source_id: str | None = None,
        domain_scores: dict | None = None,
        primary_domain: str | None = None,
        is_crystal: bool = True,
        classification_model: str | None = None,
        extraction_run_id: uuid.UUID | None = None,
    ) -> L0Chunk:
        chunk = L0Chunk(
            workspace_id=workspace_id,
            event_id=event_id,
            chunk_index=chunk_index,
            chunk_total=chunk_total,
            text=text,
            token_count=token_count,
            source_type=source_type,
            source_id=source_id,
            domain_scores=domain_scores or {},
            primary_domain=primary_domain,
            is_crystal=is_crystal,
            classification_model=classification_model,
            extraction_run_id=extraction_run_id,
        )
        self.session.add(chunk)
        await self.session.flush()
        return chunk

    async def get_by_id(self, chunk_id: uuid.UUID) -> L0Chunk | None:
        stmt = (
            select(L0Chunk)
            .join(L0Event, (L0Event.id == L0Chunk.event_id) & (L0Event.workspace_id == L0Chunk.workspace_id))
            .where(L0Chunk.id == chunk_id)
            .where(self._ws_filter(L0Chunk))
            .where(L0Event.access_level == any_(func.alaya_current_allowed_access()))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_unfiltered(self, chunk_id: uuid.UUID) -> L0Chunk | None:
        """Internal lookup that bypasses retrieval ACL while preserving workspace scope."""
        stmt = select(L0Chunk).where(L0Chunk.id == chunk_id).where(self._ws_filter(L0Chunk))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
        event_id: uuid.UUID | None = None,
        processing_stage: str | None = None,
        is_crystal: bool | None = None,
    ) -> tuple[list[L0Chunk], str | None, bool]:
        base_stmt = select(L0Chunk).where(self._ws_filter(L0Chunk))
        if event_id is not None:
            base_stmt = base_stmt.where(L0Chunk.event_id == event_id)
        if processing_stage is not None:
            base_stmt = base_stmt.where(L0Chunk.processing_stage == processing_stage)
        if is_crystal is not None:
            base_stmt = base_stmt.where(L0Chunk.is_crystal.is_(is_crystal))
        visible_stmt = base_stmt.join(
            L0Event,
            (L0Event.id == L0Chunk.event_id) & (L0Event.workspace_id == L0Chunk.workspace_id),
        ).where(L0Event.access_level == any_(func.alaya_current_allowed_access()))
        self.last_filtered_count = await self._filtered_count(base_stmt, visible_stmt)
        stmt = visible_stmt
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L0Chunk.created_at, L0Chunk.id)
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

    async def list_by_event(self, event_id: uuid.UUID) -> list[L0Chunk]:
        """List all chunks for an event ordered by chunk_index."""
        stmt = (
            select(L0Chunk)
            .where(L0Chunk.event_id == event_id)
            .where(self._ws_filter(L0Chunk))
            .order_by(L0Chunk.chunk_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_crystal(self, event_id: uuid.UUID) -> list[L0Chunk]:
        """List crystal chunks for an event that are in 'classified' stage."""
        stmt = (
            select(L0Chunk)
            .where(L0Chunk.event_id == event_id)
            .where(L0Chunk.is_crystal.is_(True))
            .where(L0Chunk.processing_stage == "classified")
            .where(self._ws_filter(L0Chunk))
            .order_by(L0Chunk.chunk_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_processing_stage(
        self,
        chunk_id: uuid.UUID,
        stage: str,
        error_message: str | None = None,
    ) -> L0Chunk | None:
        chunk = await self.get_by_id_unfiltered(chunk_id)
        if chunk is None:
            return None
        chunk.processing_stage = stage
        if error_message is not None:
            chunk.error_message = error_message
            chunk.error_count = (chunk.error_count or 0) + 1
        await self.session.flush()
        return chunk
