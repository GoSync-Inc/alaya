"""Repository for ExtractionRun — tracks LLM extraction pipeline runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from alayaos_core.models.extraction_run import ExtractionRun
from alayaos_core.models.pipeline_trace import PipelineTrace
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

    async def list_by_event(self, event_id: uuid.UUID) -> list[ExtractionRun]:
        """List all extraction runs for a specific event."""
        stmt = (
            select(ExtractionRun)
            .where(ExtractionRun.event_id == event_id)
            .where(self._ws_filter(ExtractionRun))
            .order_by(ExtractionRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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

    async def mark_failed(
        self,
        run_id: uuid.UUID,
        error_message: str,
        error_detail: dict | None = None,
    ) -> None:
        """Transition run to failed status with error info.

        Idempotent only for terminal states (completed, failed) — calling mark_failed on
        a run that has already succeeded or permanently failed is safe and has no effect.
        Intermediate states (extracting, cortex_complete) can legitimately be marked failed
        if a task crashes mid-flight; this is intentional and correct.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return
        if run.status in ("completed", "failed"):
            return
        run.status = "failed"
        run.error_message = error_message
        if error_detail is not None:
            run.error_detail = error_detail
        run.completed_at = datetime.now(UTC)
        await self.session.flush()

    async def recalc_usage(self, run_id: uuid.UUID) -> None:
        """Re-sum tokens and cost from pipeline_traces into the extraction_runs row."""
        stmt = (
            update(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .values(
                tokens_in=select(func.coalesce(func.sum(PipelineTrace.tokens_used), 0))
                .where(PipelineTrace.extraction_run_id == run_id)
                .scalar_subquery(),
                cost_usd=select(func.coalesce(func.sum(PipelineTrace.cost_usd), 0))
                .where(PipelineTrace.extraction_run_id == run_id)
                .scalar_subquery(),
            )
        )
        await self.session.execute(stmt)
