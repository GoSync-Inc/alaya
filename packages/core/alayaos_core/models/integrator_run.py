"""IntegratorRun — tracks a single integrator pass over the knowledge graph."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class IntegratorRun(Base):
    __tablename__ = "integrator_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_integrator_runs_ws_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    scope_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities_scanned: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    entities_deduplicated: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    entities_enriched: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    relations_created: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    claims_updated: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    noise_removed: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True, server_default="0.0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    status: Mapped[str | None] = mapped_column(Text, nullable=True, server_default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
