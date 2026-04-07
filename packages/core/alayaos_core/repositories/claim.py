"""Repository for L2Claim — temporal claims about entities."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from alayaos_core.models.claim import L2Claim
from alayaos_core.repositories.base import BaseRepository


class ClaimRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        entity_id: uuid.UUID,
        predicate: str,
        value: dict,
        predicate_id: uuid.UUID | None = None,
        confidence: float = 1.0,
        value_type: str = "text",
        observed_at: datetime | None = None,
        source_event_id: uuid.UUID | None = None,
        source_summary: str | None = None,
        extraction_run_id: uuid.UUID | None = None,
        supersedes: uuid.UUID | None = None,
        status: str = "active",
    ) -> L2Claim:
        claim = L2Claim(
            workspace_id=workspace_id,
            entity_id=entity_id,
            predicate=predicate,
            predicate_id=predicate_id,
            value=value,
            confidence=confidence,
            value_type=value_type,
            observed_at=observed_at,
            source_event_id=source_event_id,
            source_summary=source_summary,
            extraction_run_id=extraction_run_id,
            supersedes=supersedes,
            status=status,
        )
        self.session.add(claim)
        await self.session.flush()
        return await self.get_by_id(claim.id)  # type: ignore[return-value]

    async def get_by_id(self, claim_id: uuid.UUID) -> L2Claim | None:
        stmt = select(L2Claim).where(L2Claim.id == claim_id).where(self._ws_filter(L2Claim))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
        entity_id: uuid.UUID | None = None,
        predicate: str | None = None,
        status: str | None = None,
    ) -> tuple[list[L2Claim], str | None, bool]:
        stmt = select(L2Claim).where(self._ws_filter(L2Claim))
        if entity_id is not None:
            stmt = stmt.where(L2Claim.entity_id == entity_id)
        if predicate is not None:
            stmt = stmt.where(L2Claim.predicate == predicate)
        if status is not None:
            stmt = stmt.where(L2Claim.status == status)
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L2Claim.created_at, L2Claim.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def get_active_for_entity_predicate(self, entity_id: uuid.UUID, predicate: str) -> list[L2Claim]:
        stmt = (
            select(L2Claim)
            .where(self._ws_filter(L2Claim))
            .where(L2Claim.entity_id == entity_id)
            .where(L2Claim.predicate == predicate)
            .where(L2Claim.status == "active")
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_values_for_entity_predicate(self, entity_id: uuid.UUID, predicate: str) -> list[dict]:
        """Return just the value JSONB for dedup."""
        claims = await self.get_active_for_entity_predicate(entity_id, predicate)
        return [c.value for c in claims]

    async def update_status(self, claim_id: uuid.UUID, status: str) -> L2Claim | None:
        claim = await self.get_by_id(claim_id)
        if claim is None:
            return None
        claim.status = status
        await self.session.flush()
        return claim

    async def mark_superseded(
        self, old_claim_id: uuid.UUID, new_claim_id: uuid.UUID, valid_to: datetime
    ) -> L2Claim | None:
        """Mark old claim as superseded; set new claim's supersedes FK to old claim (per spec)."""
        old_claim = await self.get_by_id(old_claim_id)
        if old_claim is None:
            return None
        old_claim.status = "superseded"
        old_claim.valid_to = valid_to
        # Per spec: supersedes = "FK to the claim this one replaces"
        # NEW claim.supersedes → OLD claim (the one being replaced)
        new_claim = await self.get_by_id(new_claim_id)
        if new_claim:
            new_claim.supersedes = old_claim_id
        await self.session.flush()
        return old_claim
