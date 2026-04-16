"""IntegratorAction — audit record for a single consolidator action."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class IntegratorAction(Base):
    __tablename__ = "integrator_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_ia_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["integrator_runs.workspace_id", "integrator_runs.id"],
            name="fk_ia_run",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pass_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="applied", server_default="applied")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    targets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    inverse: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
