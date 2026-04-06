import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class L0Event(Base, TimestampMixin):
    __tablename__ = "l0_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_l0_events_ws_id"),
        UniqueConstraint("workspace_id", "source_type", "source_id", name="uq_l0_events_ws_src"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
