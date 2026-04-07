import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class L2Claim(Base, TimestampMixin):
    __tablename__ = "l2_claims"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_l2_claims_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_claim_entity",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "predicate_id"],
            ["predicate_definitions.workspace_id", "predicate_definitions.id"],
            name="fk_claim_predicate",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes"],
            ["l2_claims.workspace_id", "l2_claims.id"],
            name="fk_claim_supersedes",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_claim_extraction_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    predicate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("l0_events.id"), nullable=True
    )
    claim_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="text")
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ClaimSource(Base):
    """Join table — no workspace_id."""

    __tablename__ = "claim_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("l2_claims.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("l0_events.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
