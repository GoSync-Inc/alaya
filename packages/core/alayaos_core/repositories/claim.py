"""Repository for L2Claim — temporal claims about entities."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, column, func, select, table, text

from alayaos_core.models.claim import L2Claim
from alayaos_core.repositories.base import BaseRepository

_CLAIM_EFFECTIVE_ACCESS = table(
    "claim_effective_access",
    column("workspace_id"),
    column("claim_id"),
    column("max_tier_rank"),
)
_CALLER_MAX_TIER_RANK = text("(SELECT MAX(tier_rank(x)) FROM unnest(alaya_current_allowed_access()) x)")


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
        return claim

    async def get_by_id(self, claim_id: uuid.UUID) -> L2Claim | None:
        stmt = (
            select(L2Claim)
            .join(
                _CLAIM_EFFECTIVE_ACCESS,
                and_(
                    _CLAIM_EFFECTIVE_ACCESS.c.claim_id == L2Claim.id,
                    _CLAIM_EFFECTIVE_ACCESS.c.workspace_id == L2Claim.workspace_id,
                ),
            )
            .where(L2Claim.id == claim_id)
            .where(self._ws_filter(L2Claim))
            .where(_CLAIM_EFFECTIVE_ACCESS.c.max_tier_rank <= _CALLER_MAX_TIER_RANK)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_unfiltered(self, claim_id: uuid.UUID) -> L2Claim | None:
        """Internal lookup that bypasses claim visibility ACL while preserving workspace scope."""
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
        base_stmt = select(L2Claim).where(self._ws_filter(L2Claim))
        if entity_id is not None:
            base_stmt = base_stmt.where(L2Claim.entity_id == entity_id)
        if predicate is not None:
            base_stmt = base_stmt.where(L2Claim.predicate == predicate)
        if status is not None:
            base_stmt = base_stmt.where(L2Claim.status == status)
        visible_stmt = base_stmt.join(
            _CLAIM_EFFECTIVE_ACCESS,
            and_(
                _CLAIM_EFFECTIVE_ACCESS.c.claim_id == L2Claim.id,
                _CLAIM_EFFECTIVE_ACCESS.c.workspace_id == L2Claim.workspace_id,
            ),
        ).where(_CLAIM_EFFECTIVE_ACCESS.c.max_tier_rank <= _CALLER_MAX_TIER_RANK)
        self.last_filtered_count = await self._filtered_count(base_stmt, visible_stmt)
        stmt = visible_stmt
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L2Claim.created_at, L2Claim.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def _filtered_count(self, base_stmt, visible_stmt) -> int:
        total = await self.session.scalar(select(func.count()).select_from(base_stmt.subquery()))
        visible = await self.session.scalar(select(func.count()).select_from(visible_stmt.subquery()))
        return max(int(total or 0) - int(visible or 0), 0)

    async def list_unfiltered(
        self,
        cursor: str | None = None,
        limit: int = 50,
        entity_id: uuid.UUID | None = None,
        predicate: str | None = None,
        status: str | None = None,
    ) -> tuple[list[L2Claim], str | None, bool]:
        """Internal list that bypasses claim visibility ACL while preserving workspace scope."""
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
        return await self._update_status_claim(claim, status)

    async def update_status_unfiltered(self, claim_id: uuid.UUID, status: str) -> L2Claim | None:
        claim = await self.get_by_id_unfiltered(claim_id)
        return await self._update_status_claim(claim, status)

    async def _update_status_claim(self, claim: L2Claim | None, status: str) -> L2Claim | None:
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
        new_claim = await self.get_by_id(new_claim_id)
        return await self._mark_superseded_claim(old_claim, old_claim_id, new_claim, valid_to)

    async def mark_superseded_unfiltered(
        self, old_claim_id: uuid.UUID, new_claim_id: uuid.UUID, valid_to: datetime
    ) -> L2Claim | None:
        """Internal supersession that bypasses claim visibility ACL while preserving workspace scope."""
        old_claim = await self.get_by_id_unfiltered(old_claim_id)
        new_claim = await self.get_by_id_unfiltered(new_claim_id)
        return await self._mark_superseded_claim(old_claim, old_claim_id, new_claim, valid_to)

    async def _mark_superseded_claim(
        self,
        old_claim: L2Claim | None,
        old_claim_id: uuid.UUID,
        new_claim: L2Claim | None,
        valid_to: datetime,
    ) -> L2Claim | None:
        """Mark old claim as superseded; set new claim's supersedes FK to old claim."""
        if old_claim is None:
            return None
        old_claim.status = "superseded"
        old_claim.valid_to = valid_to
        # Per spec: supersedes = "FK to the claim this one replaces"
        # NEW claim.supersedes → OLD claim (the one being replaced)
        if new_claim:
            new_claim.supersedes = old_claim_id
        await self.session.flush()
        return old_claim
