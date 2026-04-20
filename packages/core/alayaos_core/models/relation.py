import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class L1Relation(Base, TimestampMixin):
    __tablename__ = "l1_relations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_l1_relations_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "source_entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_relation_source_entity",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "target_entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_relation_target_entity",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_relation_extraction_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    relation_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RelationSource(Base):
    """Join table — workspace_id added in migration 007."""

    __tablename__ = "relation_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "relation_id"],
            ["l1_relations.workspace_id", "l1_relations.id"],
            name="fk_relation_sources_relation",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["l0_events.workspace_id", "l0_events.id"],
            name="fk_relation_sources_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
