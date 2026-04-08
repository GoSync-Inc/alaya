"""Repository for vector_chunks table."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.vector import VectorChunk
from alayaos_core.repositories.base import BaseRepository


class VectorChunkRepository(BaseRepository):
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        super().__init__(session, workspace_id)

    async def upsert_chunks(self, chunks: list[dict]) -> int:
        """Batch upsert vector chunks. Deletes existing by source, then inserts."""
        if not chunks:
            return 0
        # Group by source to delete existing
        seen_sources: set[tuple[str, str]] = set()
        for chunk in chunks:
            seen_sources.add((chunk["source_type"], str(chunk["source_id"])))

        for source_type, source_id in seen_sources:
            stmt = select(VectorChunk).where(
                self._ws_filter(VectorChunk),
                VectorChunk.source_type == source_type,
                VectorChunk.source_id == uuid.UUID(source_id),
            )
            result = await self.session.execute(stmt)
            for existing in result.scalars().all():
                await self.session.delete(existing)

        await self.session.flush()

        for chunk in chunks:
            self.session.add(VectorChunk(**chunk))

        await self.session.flush()
        return len(chunks)

    async def get_by_source(self, source_type: str, source_id: uuid.UUID) -> list[VectorChunk]:
        """Get chunks by source (to check existence for skip logic)."""
        stmt = select(VectorChunk).where(
            self._ws_filter(VectorChunk),
            VectorChunk.source_type == source_type,
            VectorChunk.source_id == source_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
