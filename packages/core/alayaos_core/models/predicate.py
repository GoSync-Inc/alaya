import uuid

from sqlalchemy import ARRAY, Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class PredicateDefinition(Base, TimestampMixin):
    __tablename__ = "predicate_definitions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_predicate_ws_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="text"
    )  # 'text','date','number','boolean','entity_ref','json'
    domain_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    cardinality: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="many"
    )  # 'one' or 'many'
    inverse_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_core: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
