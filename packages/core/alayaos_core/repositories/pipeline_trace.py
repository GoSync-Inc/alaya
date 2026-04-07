"""Repository for PipelineTrace — audit log for intelligence pipeline stages."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from alayaos_core.models.pipeline_trace import PipelineTrace
from alayaos_core.repositories.base import BaseRepository


class PipelineTraceRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        event_id: uuid.UUID,
        stage: str,
        decision: str,
        reason: str | None = None,
        details: dict | None = None,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
        extraction_run_id: uuid.UUID | None = None,
    ) -> PipelineTrace:
        trace = PipelineTrace(
            workspace_id=workspace_id,
            event_id=event_id,
            stage=stage,
            decision=decision,
            reason=reason,
            details=details or {},
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            extraction_run_id=extraction_run_id,
        )
        self.session.add(trace)
        await self.session.flush()
        return trace

    async def list_by_event(self, event_id: uuid.UUID) -> list[PipelineTrace]:
        """List all traces for an event ordered by created_at."""
        stmt = (
            select(PipelineTrace)
            .where(PipelineTrace.event_id == event_id)
            .where(self._ws_filter(PipelineTrace))
            .order_by(PipelineTrace.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
