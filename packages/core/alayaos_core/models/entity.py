import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alayaos_core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from alayaos_core.models.entity_type import EntityTypeDefinition


class L1Entity(Base, TimestampMixin):
    __tablename__ = "l1_entities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_l1_entities_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "entity_type_id"],
            ["entity_type_definitions.workspace_id", "entity_type_definitions.id"],
            name="fk_entities_type",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "extraction_run_id"],
            ["extraction_runs.workspace_id", "extraction_runs.id"],
            name="fk_entity_extraction_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    entity_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    entity_type: Mapped["EntityTypeDefinition"] = relationship("EntityTypeDefinition", lazy="raise")
    external_ids: Mapped[list["EntityExternalId"]] = relationship(
        "EntityExternalId", back_populates="entity", lazy="select"
    )


class EntityExternalId(Base):
    __tablename__ = "entity_external_ids"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "entity_id",
            "source_type",
            "external_id",
            name="uq_entity_ext_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_ext_id_entity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    entity: Mapped["L1Entity"] = relationship("L1Entity", back_populates="external_ids", lazy="raise")
