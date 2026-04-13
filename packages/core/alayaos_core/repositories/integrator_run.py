"""Repository for IntegratorRun — tracks integrator passes over the knowledge graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from alayaos_core.models.integrator_run import IntegratorRun
from alayaos_core.repositories.base import BaseRepository


class IntegratorRunRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        trigger: str,
        scope_description: str | None = None,
        llm_model: str | None = None,
    ) -> IntegratorRun:
        run = IntegratorRun(
            workspace_id=workspace_id,
            trigger=trigger,
            scope_description=scope_description,
            llm_model=llm_model,
        )
        self.session.add(run)
        await self.session.flush()
        return await self.get_by_id(run.id)  # type: ignore[return-value]

    async def get_by_id(self, run_id: uuid.UUID) -> IntegratorRun | None:
        stmt = select(IntegratorRun).where(IntegratorRun.id == run_id).where(self._ws_filter(IntegratorRun))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[IntegratorRun], str | None, bool]:
        stmt = select(IntegratorRun).where(self._ws_filter(IntegratorRun))
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, IntegratorRun.started_at, IntegratorRun.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].started_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def update_status(
        self,
        run_id: uuid.UUID,
        status: str,
        error_message: str | None = None,
    ) -> IntegratorRun | None:
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = status
        if status == "failed":
            run.error_message = error_message
        else:
            run.error_message = None
        if status in ("completed", "failed", "skipped"):
            run.completed_at = datetime.now(UTC)
        await self.session.flush()
        return run

    async def update_counters(
        self,
        run_id: uuid.UUID,
        entities_scanned: int = 0,
        entities_deduplicated: int = 0,
        entities_enriched: int = 0,
        relations_created: int = 0,
        claims_updated: int = 0,
        noise_removed: int = 0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
    ) -> IntegratorRun | None:
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.entities_scanned = entities_scanned
        run.entities_deduplicated = entities_deduplicated
        run.entities_enriched = entities_enriched
        run.relations_created = relations_created
        run.claims_updated = claims_updated
        run.noise_removed = noise_removed
        run.tokens_used = tokens_used
        run.cost_usd = cost_usd
        run.duration_ms = duration_ms
        await self.session.flush()
        return run

    async def mark_stale_running_failed(
        self,
        *,
        started_before: datetime,
        error_message: str,
        exclude_run_id: uuid.UUID | None = None,
    ) -> int:
        stmt = (
            select(IntegratorRun)
            .where(self._ws_filter(IntegratorRun))
            .where(IntegratorRun.status == "running")
            .where(IntegratorRun.completed_at.is_(None))
            .where(IntegratorRun.started_at < started_before)
        )
        if exclude_run_id is not None:
            stmt = stmt.where(IntegratorRun.id != exclude_run_id)

        result = await self.session.execute(stmt)
        runs = list(result.scalars().all())
        if not runs:
            return 0

        completed_at = datetime.now(UTC)
        for run in runs:
            run.status = "failed"
            run.error_message = error_message
            run.completed_at = completed_at

        await self.session.flush()
        return len(runs)
