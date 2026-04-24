"""Repository for L1Relation — entity-to-entity relationships."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select

from alayaos_core.models.entity import L1Entity
from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.models.relation import L1Relation
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.services.workspace import ENTITY_TYPE_TIER_RANK


class RelationRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        relation_type: str,
        confidence: float = 1.0,
        extraction_run_id: uuid.UUID | None = None,
    ) -> L1Relation:
        await self._validate_relation(
            workspace_id=workspace_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
        )
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
        """Bulk create relations. Flushes once after all inserts."""
        for rel_data in relations:
            await self._validate_relation(
                workspace_id=workspace_id,
                source_entity_id=rel_data["source_entity_id"],
                target_entity_id=rel_data["target_entity_id"],
                relation_type=rel_data["relation_type"],
            )

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

    async def _validate_relation(
        self,
        *,
        workspace_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        relation_type: str,
    ) -> None:
        if relation_type != "part_of":
            return

        if source_entity_id == target_entity_id:
            raise ValueError("part_of relation cannot reference the same entity on both sides")

        type_slugs = await self._get_entity_type_slugs(
            workspace_id=workspace_id,
            entity_ids={source_entity_id, target_entity_id},
        )

        child_rank = ENTITY_TYPE_TIER_RANK.get(type_slugs.get(source_entity_id, ""))
        parent_rank = ENTITY_TYPE_TIER_RANK.get(type_slugs.get(target_entity_id, ""))
        if child_rank is None or parent_rank is None:
            return

        if parent_rank <= child_rank:
            raise ValueError("part_of relation must point from a lower-tier child to a higher-tier parent")

    async def _get_entity_type_slugs(
        self,
        *,
        workspace_id: uuid.UUID,
        entity_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        if not entity_ids:
            return {}

        stmt = (
            select(L1Entity.id, EntityTypeDefinition.slug)
            .join(
                EntityTypeDefinition,
                (EntityTypeDefinition.workspace_id == L1Entity.workspace_id)
                & (EntityTypeDefinition.id == L1Entity.entity_type_id),
            )
            .where(L1Entity.workspace_id == workspace_id)
            .where(L1Entity.id.in_(entity_ids))
        )
        result = await self.session.execute(stmt)
        return dict(result.all())
