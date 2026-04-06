import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alayaos_core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from alayaos_core.models.entity_type import EntityTypeDefinition


class L1Entity(Base, TimestampMixin):
    __tablename__ = "l1_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_type_definitions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entity_type: Mapped["EntityTypeDefinition"] = relationship("EntityTypeDefinition", lazy="select")
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
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("l1_entities.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    entity: Mapped["L1Entity"] = relationship("L1Entity", back_populates="external_ids")
