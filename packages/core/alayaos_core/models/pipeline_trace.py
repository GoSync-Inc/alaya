"""PipelineTrace — audit trail for each stage of the intelligence pipeline."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class PipelineTrace(Base):
    __tablename__ = "pipeline_traces"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_pipeline_traces_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_trace_event",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_trace_run",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "integrator_run_id"],
            ["integrator_runs.workspace_id", "integrator_runs.id"],
            name="fk_trace_integrator_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Nullable: traces may be scoped to event (cortex/crystallizer) or integrator run
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    integrator_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="{}")
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    # Granular token classes (migration 009)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_5m_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_1h_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True, server_default="0.0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
