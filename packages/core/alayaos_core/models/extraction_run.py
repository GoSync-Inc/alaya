import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class ExtractionRun(Base, TimestampMixin):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_extraction_runs_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_extraction_run_event",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "parent_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_extraction_run_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    raw_extraction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entities_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    entities_merged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    relations_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claims_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    claims_superseded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    resolver_decisions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chunks_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    chunks_crystal: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    chunks_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cortex_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    crystallizer_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    verification_changes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
