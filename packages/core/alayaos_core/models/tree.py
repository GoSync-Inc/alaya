# STUB — no repository until Run 3
import uuid

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base, TimestampMixin


class L3TreeNode(Base, TimestampMixin):
    __tablename__ = "l3_tree_nodes"
    __table_args__ = (UniqueConstraint("workspace_id", "path", name="uq_tree_node_ws_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("l1_entities.id"), nullable=True)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
