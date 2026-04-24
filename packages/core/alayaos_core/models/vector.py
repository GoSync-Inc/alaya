import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Computed, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class VectorChunk(Base):
    __tablename__ = "vector_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(1024), nullable=True)
    tsv: Mapped[None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True), nullable=True
    )
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    access_level: Mapped[str] = mapped_column(Text, nullable=False, server_default="restricted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
