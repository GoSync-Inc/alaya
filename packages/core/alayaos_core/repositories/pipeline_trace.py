"""Repository for PipelineTrace — audit log for intelligence pipeline stages."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from alayaos_core.models.pipeline_trace import PipelineTrace
from alayaos_core.repositories.base import BaseRepository

_SENTINEL = object()  # sentinel for detecting "not passed" vs 0


class PipelineTraceRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        event_id: uuid.UUID | None = None,
        stage: str = "",
        decision: str = "",
        reason: str | None = None,
        details: dict | None = None,
        # Legacy kwarg: if explicitly passed, overrides the auto-compute.
        tokens_used: object = _SENTINEL,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
        extraction_run_id: uuid.UUID | None = None,
        # Granular token-class kwargs (migration 009)
        tokens_in: int = 0,
        tokens_out: int = 0,
        tokens_cached: int = 0,
        cache_write_5m_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
        integrator_run_id: uuid.UUID | None = None,
    ) -> PipelineTrace:
        # tokens_used policy: auto-compute = tokens_in + tokens_out unless caller overrides.
        computed_tokens_used = tokens_in + tokens_out if tokens_used is _SENTINEL else int(tokens_used)  # type: ignore[arg-type]

        trace = PipelineTrace(
            workspace_id=workspace_id,
            event_id=event_id,
            stage=stage,
            decision=decision,
            reason=reason,
            details=details or {},
            tokens_used=computed_tokens_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            extraction_run_id=extraction_run_id,
            integrator_run_id=integrator_run_id,
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

    async def list_by_integrator_run(self, integrator_run_id: uuid.UUID) -> list[PipelineTrace]:
        """List all traces for an integrator run ordered by created_at."""
        stmt = (
            select(PipelineTrace)
            .where(PipelineTrace.integrator_run_id == integrator_run_id)
            .where(self._ws_filter(PipelineTrace))
            .order_by(PipelineTrace.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
