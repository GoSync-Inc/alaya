import uuid
from typing import ClassVar

from sqlalchemy import Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from alayaos_core.models.base import Base


class ClaimEffectiveAccess(Base):
    """Read-only ORM binding for the claim_effective_access database view."""

    __tablename__ = "claim_effective_access"
    __table_args__: ClassVar[dict[str, dict[str, bool]]] = {"info": {"read_only": True}}

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    max_tier_rank: Mapped[int] = mapped_column(Integer, nullable=False)
