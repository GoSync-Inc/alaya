"""Repository for L0Chunk — chunked events for the Cortex pipeline."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from alayaos_core.models.chunk import L0Chunk
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
        return await self.get_by_id(chunk.id)  # type: ignore[return-value]

    async def get_by_id(self, chunk_id: uuid.UUID) -> L0Chunk | None:
        stmt = select(L0Chunk).where(L0Chunk.id == chunk_id).where(self._ws_filter(L0Chunk))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[L0Chunk], str | None, bool]:
        stmt = select(L0Chunk).where(self._ws_filter(L0Chunk))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L0Chunk.created_at, L0Chunk.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

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
        chunk = await self.get_by_id(chunk_id)
        if chunk is None:
            return None
        chunk.processing_stage = stage
        if error_message is not None:
            chunk.error_message = error_message
            chunk.error_count = (chunk.error_count or 0) + 1
        await self.session.flush()
        return chunk
