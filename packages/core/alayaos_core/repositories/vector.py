"""Repository for vector_chunks table."""

import uuid
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.vector import VectorChunk
from alayaos_core.repositories.base import BaseRepository

_RANK_TO_ACCESS_LEVEL = {
    0: "public",
    1: "channel",
    2: "private",
    3: "restricted",
}
_VALID_ACCESS_LEVELS = set(_RANK_TO_ACCESS_LEVEL.values())
VectorChunkPayload = dict[str, Any]


class VectorChunkRepository(BaseRepository):
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        super().__init__(session, workspace_id)

    async def create_batch(self, chunks: list[VectorChunkPayload]) -> int:
        """Batch upsert vector chunks. Deletes existing by source, then inserts."""
        if not chunks:
            return 0

        for index, chunk in enumerate(chunks):
            if "access_level" not in chunk:
                raise ValueError(f"vector chunk at index {index} missing access_level")

        # Group by source to delete existing
        seen_sources: set[tuple[str, str]] = set()
        for chunk in chunks:
            seen_sources.add((chunk["source_type"], str(chunk["source_id"])))

        for source_type, source_id in seen_sources:
            where_clauses = [
                VectorChunk.source_type == source_type,
                VectorChunk.source_id == uuid.UUID(source_id),
            ]
            if self.workspace_id is not None:
                where_clauses.append(VectorChunk.workspace_id == self.workspace_id)
            stmt = select(VectorChunk).where(*where_clauses)
            result = await self.session.execute(stmt)
            for existing in result.scalars().all():
                await self.session.delete(existing)

        await self.session.flush()

        for chunk in chunks:
            chunk_data: VectorChunkPayload = dict(chunk)
            access_level = chunk_data.pop("access_level")
            vector_chunk = VectorChunk(**chunk_data)
            cast("Any", vector_chunk).access_level = access_level
            self.session.add(vector_chunk)

        await self.session.flush()
        return len(chunks)

    async def upsert_chunks(self, chunks: list[VectorChunkPayload]) -> int:
        """Backward-compatible alias for callers that still use the old name."""
        return await self.create_batch(chunks)

    async def get_access_level_for_source(self, source_type: str, source_id: uuid.UUID) -> str:
        """Return the insert-time ACL for a vector chunk source."""
        if source_type == "claim":
            rank = await self._get_claim_source_rank(source_id)
            return _RANK_TO_ACCESS_LEVEL[rank if rank is not None else 3]
        if source_type == "entity":
            rank = await self._get_entity_source_rank(source_id)
            return _RANK_TO_ACCESS_LEVEL[rank if rank is not None else 3]
        if source_type == "event":
            access_level = await self._get_event_access_level(source_id)
            return access_level if access_level in _VALID_ACCESS_LEVELS else "restricted"
        return "restricted"

    async def _get_claim_source_rank(self, claim_id: uuid.UUID) -> int | None:
        result = await self.session.execute(
            text(
                """
                SELECT MAX(
                    CASE e.access_level
                        WHEN 'restricted' THEN 3
                        WHEN 'private' THEN 2
                        WHEN 'channel' THEN 1
                        WHEN 'public' THEN 0
                        ELSE 3
                    END
                )
                FROM claim_sources cs
                JOIN l0_events e
                  ON e.workspace_id = cs.workspace_id
                 AND e.id = cs.event_id
                WHERE cs.workspace_id = :workspace_id
                  AND cs.claim_id = :claim_id
                """
            ),
            {"workspace_id": self.workspace_id, "claim_id": claim_id},
        )
        return result.scalar_one_or_none()

    async def _get_entity_source_rank(self, entity_id: uuid.UUID) -> int | None:
        result = await self.session.execute(
            text(
                """
                SELECT MAX(
                    CASE e.access_level
                        WHEN 'restricted' THEN 3
                        WHEN 'private' THEN 2
                        WHEN 'channel' THEN 1
                        WHEN 'public' THEN 0
                        ELSE 3
                    END
                )
                FROM l2_claims c
                JOIN claim_sources cs
                  ON cs.workspace_id = c.workspace_id
                 AND cs.claim_id = c.id
                JOIN l0_events e
                  ON e.workspace_id = cs.workspace_id
                 AND e.id = cs.event_id
                WHERE c.workspace_id = :workspace_id
                  AND c.entity_id = :entity_id
                """
            ),
            {"workspace_id": self.workspace_id, "entity_id": entity_id},
        )
        return result.scalar_one_or_none()

    async def _get_event_access_level(self, event_id: uuid.UUID) -> str | None:
        result = await self.session.execute(
            text(
                """
                SELECT access_level
                FROM l0_events
                WHERE workspace_id = :workspace_id
                  AND id = :event_id
                """
            ),
            {"workspace_id": self.workspace_id, "event_id": event_id},
        )
        return result.scalar_one_or_none()

    async def get_by_source(self, source_type: str, source_id: uuid.UUID) -> list[VectorChunk]:
        """Get chunks by source (to check existence for skip logic)."""
        where_clauses = [
            VectorChunk.source_type == source_type,
            VectorChunk.source_id == source_id,
        ]
        if self.workspace_id is not None:
            where_clauses.append(VectorChunk.workspace_id == self.workspace_id)
        stmt = select(VectorChunk).where(*where_clauses)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
