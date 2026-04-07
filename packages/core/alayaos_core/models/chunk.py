"""L0Chunk — chunked representation of an L0Event for the Cortex pipeline."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class L0Chunk(Base):
    __tablename__ = "l0_chunks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_l0_chunks_ws_id"),
        UniqueConstraint("workspace_id", "event_id", "chunk_index", name="uq_l0_chunks_ws_event_idx"),
        ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_chunk_event",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_chunk_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_total: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    primary_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_crystal: Mapped[bool | None] = mapped_column(Boolean, nullable=True, server_default="true")
    classification_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True, server_default="false")
    verification_changed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, server_default="false")
    processing_stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="classified")
    error_count: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
