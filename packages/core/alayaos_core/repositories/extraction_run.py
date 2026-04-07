"""Repository for ExtractionRun — tracks LLM extraction pipeline runs."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from alayaos_core.models.extraction_run import ExtractionRun
from alayaos_core.repositories.base import BaseRepository


class ExtractionRunRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        event_id: uuid.UUID | None = None,
        status: str = "pending",
        parent_run_id: uuid.UUID | None = None,
    ) -> ExtractionRun:
        run = ExtractionRun(
            workspace_id=workspace_id,
            event_id=event_id,
            status=status,
            parent_run_id=parent_run_id,
        )
        self.session.add(run)
        await self.session.flush()
        return await self.get_by_id(run.id)  # type: ignore[return-value]

    async def get_by_id(self, run_id: uuid.UUID) -> ExtractionRun | None:
        stmt = select(ExtractionRun).where(ExtractionRun.id == run_id).where(self._ws_filter(ExtractionRun))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[ExtractionRun], str | None, bool]:
        stmt = select(ExtractionRun).where(self._ws_filter(ExtractionRun))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, ExtractionRun.created_at, ExtractionRun.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def update_status(
        self,
        run_id: uuid.UUID,
        status: str,
        error_message: str | None = None,
        error_detail: dict | None = None,
    ) -> ExtractionRun | None:
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = status
        if error_message is not None:
            run.error_message = error_message
        if error_detail is not None:
            run.error_detail = error_detail
        await self.session.flush()
        return run

    async def update_counters(
        self,
        run_id: uuid.UUID,
        entities_created: int,
        entities_merged: int,
        relations_created: int,
        claims_created: int,
        claims_superseded: int,
    ) -> ExtractionRun | None:
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.entities_created = entities_created
        run.entities_merged = entities_merged
        run.relations_created = relations_created
        run.claims_created = claims_created
        run.claims_superseded = claims_superseded
        await self.session.flush()
        return run

    async def store_raw_extraction(self, run_id: uuid.UUID, raw_extraction: dict) -> ExtractionRun | None:
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.raw_extraction = raw_extraction
        await self.session.flush()
        return run

    async def clear_raw_extraction(self, run_id: uuid.UUID) -> ExtractionRun | None:
        """Set raw_extraction to None after Job 2 processing is complete."""
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.raw_extraction = None
        await self.session.flush()
        return run
