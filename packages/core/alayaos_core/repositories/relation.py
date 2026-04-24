"""Repository for L1Relation — entity-to-entity relationships."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import or_, select, text

from alayaos_core.config import get_settings
from alayaos_core.models.relation import L1Relation
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.errors import HierarchyViolationError
from alayaos_core.services.workspace import ENTITY_TYPE_TIER_RANK

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_PART_OF_SLUG_QUERY = text(
    """
    SELECT
        se.id           AS source_entity_id,
        sd.slug         AS source_slug,
        te.id           AS target_entity_id,
        td.slug         AS target_slug
    FROM l1_entities se
    JOIN entity_type_definitions sd
        ON sd.id = se.entity_type_id AND sd.workspace_id = se.workspace_id
    JOIN l1_entities te
        ON te.id = :target_entity_id AND te.workspace_id = :workspace_id
    JOIN entity_type_definitions td
        ON td.id = te.entity_type_id AND td.workspace_id = te.workspace_id
    WHERE se.id = :source_entity_id
      AND se.workspace_id = :workspace_id
    """
)


def _reject_self_reference(source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """Raise HierarchyViolationError if source_id == target_id."""
    if source_id == target_id:
        raise HierarchyViolationError("relation cannot be self-referential")


class RelationRepository(BaseRepository):
    async def _validate_part_of_tier(
        self,
        session,
        workspace_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
    ) -> None:
        """Validate ENTITY_TYPE_TIER_RANK for a part_of relation.

        If both entity type slugs are in ENTITY_TYPE_TIER_RANK and
        source_rank >= target_rank, raise HierarchyViolationError.
        If either slug is absent from the rank table, silently pass.
        """
        mode = get_settings().ALAYA_PART_OF_STRICT
        if mode == "off":
            return

        result = await session.execute(
            _PART_OF_SLUG_QUERY,
            {
                "workspace_id": workspace_id,
                "source_entity_id": source_entity_id,
                "target_entity_id": target_entity_id,
            },
        )
        row = result.mappings().first()
        if row is None:
            return  # entities not found — let DB constraints handle it

        source_slug = row["source_slug"]
        target_slug = row["target_slug"]

        source_rank = ENTITY_TYPE_TIER_RANK.get(source_slug)
        target_rank = ENTITY_TYPE_TIER_RANK.get(target_slug)

        if source_rank is None or target_rank is None:
            return  # non-tiered type — allowed

        if source_rank >= target_rank:
            message = f"part_of: {source_slug}({source_rank}) cannot be part_of {target_slug}({target_rank})"
            if mode == "warn":
                log.warning(
                    "part_of.tier_violation",
                    workspace_id=str(workspace_id),
                    source_entity_id=str(source_entity_id),
                    target_entity_id=str(target_entity_id),
                    source_slug=source_slug,
                    target_slug=target_slug,
                    source_rank=source_rank,
                    target_rank=target_rank,
                    mode="warn",
                )
                return
            raise HierarchyViolationError(message)

    async def create(
        self,
        workspace_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        relation_type: str,
        confidence: float = 1.0,
        extraction_run_id: uuid.UUID | None = None,
    ) -> L1Relation:
        _reject_self_reference(source_entity_id, target_entity_id)
        if relation_type == "part_of":
            await self._validate_part_of_tier(self.session, workspace_id, source_entity_id, target_entity_id)

        relation = L1Relation(
            workspace_id=workspace_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            confidence=confidence,
            extraction_run_id=extraction_run_id,
        )
        self.session.add(relation)
        await self.session.flush()
        return await self.get_by_id(relation.id)  # type: ignore[return-value]

    async def get_by_id(self, relation_id: uuid.UUID) -> L1Relation | None:
        stmt = select(L1Relation).where(L1Relation.id == relation_id).where(self._ws_filter(L1Relation))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        cursor: str | None = None,
        limit: int = 50,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[list[L1Relation], str | None, bool]:
        stmt = select(L1Relation).where(self._ws_filter(L1Relation))
        if entity_id is not None:
            # Filter matches either source or target entity
            stmt = stmt.where(
                or_(
                    L1Relation.source_entity_id == entity_id,
                    L1Relation.target_entity_id == entity_id,
                )
            )
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, L1Relation.created_at, L1Relation.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def create_batch(self, workspace_id: uuid.UUID, relations: list[dict]) -> list[L1Relation]:
        """Bulk create relations. Validates ALL rows before any session.add."""
        # Validate all rows first — batch fails atomically if any row is invalid
        for rel_data in relations:
            source_id = rel_data["source_entity_id"]
            target_id = rel_data["target_entity_id"]
            _reject_self_reference(source_id, target_id)
            if rel_data["relation_type"] == "part_of":
                await self._validate_part_of_tier(self.session, workspace_id, source_id, target_id)

        # All validations passed — now insert
        created = []
        for rel_data in relations:
            relation = L1Relation(
                workspace_id=workspace_id,
                source_entity_id=rel_data["source_entity_id"],
                target_entity_id=rel_data["target_entity_id"],
                relation_type=rel_data["relation_type"],
                confidence=rel_data.get("confidence", 1.0),
                extraction_run_id=rel_data.get("extraction_run_id"),
            )
            self.session.add(relation)
            created.append(relation)
        await self.session.flush()
        return created
