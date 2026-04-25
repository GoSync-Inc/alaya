"""Knowledge tree service — briefing synthesis with dirty-flag rebuild."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, text

from alayaos_core.repositories.tree import TreeNodeRepository
from alayaos_core.schemas.tree import TreeBriefing, TreeNodeView

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.llm.interface import LLMServiceInterface

log = structlog.get_logger()

BRIEFING_TIMEOUT = 6  # seconds
_TIER_RANK = {"public": 0, "channel": 1, "private": 2, "restricted": 3}


class TreeService:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        llm: LLMServiceInterface | None = None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._repo = TreeNodeRepository(session, workspace_id)
        self._llm = llm

    async def get_node(self, path: str, allowed_tiers: set[str]) -> TreeNodeView | None:
        """Get a tree node, rebuilding cached briefing only for admin callers."""
        node = await self._repo.get_by_path(path)

        if not node:
            return None

        if node.entity_id and not await self._entity_visible(node.entity_id, allowed_tiers):
            return None

        if "restricted" not in allowed_tiers:
            return await self._render_live_filtered(node, allowed_tiers)

        if node.is_dirty and self._llm:
            await self._rebuild_briefing(node)
        return self._node_view(node, summary=node.summary, markdown_cache=node.markdown_cache)

    async def get_children(self, path: str):
        return await self._repo.get_children(path)

    async def get_root(self):
        """Get root-level tree nodes (entity type categories)."""
        return await self._repo.get_children("")

    async def build_tree(self) -> int:
        """Scaffold index nodes from entity types. Returns count of nodes created."""
        from alayaos_core.repositories.entity_type import EntityTypeRepository

        type_repo = EntityTypeRepository(self._session, self._workspace_id)
        types = await type_repo.get_all()

        count = 0
        for et in types:
            await self._repo.upsert_node(
                workspace_id=self._workspace_id,
                path=et.slug,
                node_type="index",
            )
            count += 1

        return count

    async def _rebuild_briefing(self, node) -> None:
        """Rebuild briefing for a dirty node with timeout + fallback."""
        from sqlalchemy import select

        from alayaos_core.models.claim import L2Claim
        from alayaos_core.models.entity import L1Entity

        if not node.entity_id:
            # Index node — just clear dirty
            node.is_dirty = False
            node.last_rebuilt_at = datetime.now(UTC)
            await self._session.flush()
            return

        # Load entity with FOR UPDATE to prevent concurrent rebuilds
        entity_stmt = select(L1Entity).where(L1Entity.id == node.entity_id).with_for_update()
        entity = (await self._session.execute(entity_stmt)).scalar_one_or_none()
        if not entity:
            node.is_dirty = False
            await self._session.flush()
            return

        claim_stmt = select(L2Claim).where(
            L2Claim.workspace_id == self._workspace_id,
            L2Claim.entity_id == entity.id,
            L2Claim.status == "active",
        )
        claims = list((await self._session.execute(claim_stmt)).scalars().all())

        # Try LLM synthesis with timeout
        try:
            briefing = await asyncio.wait_for(
                self._synthesize_briefing(entity, claims),
                timeout=BRIEFING_TIMEOUT,
            )
            node.markdown_cache = self._render_briefing_markdown(briefing)
            node.summary = briefing.model_dump()
        except (TimeoutError, Exception) as e:
            log.warning("briefing_synthesis_failed", entity_id=str(entity.id), error=str(e))
            node.markdown_cache = self._render_raw_claims_markdown(entity, claims)
            node.summary = {}

        node.is_dirty = False
        node.last_rebuilt_at = datetime.now(UTC)
        await self._session.flush()

    async def _entity_visible(self, entity_id: uuid.UUID, allowed_tiers: set[str]) -> bool:
        stmt = text("""
            SELECT EXISTS (
                SELECT 1
                FROM l2_claims c
                JOIN claim_effective_access cea
                  ON cea.claim_id = c.id AND cea.workspace_id = c.workspace_id
                WHERE c.entity_id = :entity_id
                  AND c.workspace_id = :ws_id
                  AND c.status = 'active'
                  AND cea.max_tier_rank <= :max_tier_rank
            )
        """)
        result = await self._session.execute(
            stmt,
            {
                "entity_id": entity_id,
                "ws_id": self._workspace_id,
                "max_tier_rank": _max_tier_rank(allowed_tiers),
            },
        )
        return bool(result.scalar())

    async def _render_live_filtered(self, node, allowed_tiers: set[str]) -> TreeNodeView:
        if not node.entity_id:
            return self._node_view(node, summary=None, markdown_cache=None)

        claims = await self._get_filtered_claims(node.entity_id, allowed_tiers)
        entity = await self._load_entity(node.entity_id)
        if entity is None:
            return self._node_view(node, summary=None, markdown_cache=None)

        live_markdown = self._render_raw_claims_markdown(entity, claims, include_description=False)
        return self._node_view(node, summary=None, markdown_cache=live_markdown)

    async def _get_filtered_claims(self, entity_id: uuid.UUID, allowed_tiers: set[str]):
        stmt = text("""
            SELECT c.id, c.predicate, c.value, c.confidence, c.valid_from, c.valid_to
            FROM l2_claims c
            JOIN claim_effective_access cea
              ON cea.claim_id = c.id AND cea.workspace_id = c.workspace_id
            WHERE c.workspace_id = :ws_id
              AND c.entity_id = :entity_id
              AND c.status = 'active'
              AND cea.max_tier_rank <= :max_tier_rank
            ORDER BY c.observed_at DESC NULLS LAST, c.created_at DESC
        """)
        result = await self._session.execute(
            stmt,
            {
                "ws_id": self._workspace_id,
                "entity_id": entity_id,
                "max_tier_rank": _max_tier_rank(allowed_tiers),
            },
        )
        return list(result.mappings().all())

    async def _load_entity(self, entity_id: uuid.UUID):
        from alayaos_core.models.entity import L1Entity

        stmt = select(L1Entity).where(
            L1Entity.workspace_id == self._workspace_id,
            L1Entity.id == entity_id,
            L1Entity.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _synthesize_briefing(self, entity, claims) -> TreeBriefing:
        """Use LLM to synthesize a briefing from entity + claims."""
        claims_text = "\n".join(
            f"- {c.predicate}: {c.value} (confidence: {c.confidence})"
            for c in claims[:50]  # TREE_MAX_CLAIMS_PER_BRIEF
        )

        system_prompt = (
            "You are a corporate knowledge assistant. Generate a concise operational briefing "
            "for the given entity based on its claims. Return structured JSON."
        )
        text = f"Entity: {entity.name}\nType: {entity.entity_type_id}\n\nClaims:\n{claims_text}"

        briefing, _ = await self._llm.extract(
            text=text,
            system_prompt=system_prompt,
            response_model=TreeBriefing,
            max_tokens=1024,
            stage="tree:briefing",
        )
        return briefing

    @staticmethod
    def _render_briefing_markdown(briefing: TreeBriefing) -> str:
        lines = [f"# {briefing.title}", "", briefing.summary, ""]
        if briefing.key_facts:
            lines.append("## Key Facts")
            for fact in briefing.key_facts:
                lines.append(f"- {fact}")
        if briefing.status:
            lines.extend(["", f"**Status:** {briefing.status}"])
        return "\n".join(lines)

    @staticmethod
    def _render_raw_claims_markdown(entity, claims, *, include_description: bool = True) -> str:
        lines = [f"# {entity.name}", ""]
        if include_description and entity.description:
            lines.extend([entity.description, ""])
        lines.append("## Claims")
        for c in claims:
            lines.append(f"- **{_claim_field(c, 'predicate')}**: {_claim_field(c, 'value')}")
        return "\n".join(lines)

    def _node_view(self, node, *, summary: dict | None, markdown_cache: str | None) -> TreeNodeView:
        return TreeNodeView(
            id=node.id,
            path=node.path,
            workspace_id=node.workspace_id,
            entity_id=node.entity_id,
            node_type=node.node_type,
            is_dirty=node.is_dirty,
            last_rebuilt_at=node.last_rebuilt_at,
            markdown_cache=markdown_cache,
            summary=summary,
        )

    async def export_subtree(self, path: str, allowed_tiers: set[str]) -> str:
        """Export subtree as markdown."""
        nodes = await self._repo.get_children(path, depth=99)
        root_node = await self._repo.get_by_path(path)
        export_nodes = ([root_node] if root_node else []) + nodes

        if not export_nodes:
            return f"# {path}\n\nNo content available."

        parts = []
        if "restricted" in allowed_tiers:
            for node in export_nodes:
                if node.markdown_cache:
                    parts.append(node.markdown_cache)
                else:
                    parts.append(f"## {node.path}")
        else:
            for node in export_nodes:
                view = await self.get_node(node.path, allowed_tiers=allowed_tiers)
                if view and view.markdown_cache:
                    parts.append(view.markdown_cache)

        return "\n\n---\n\n".join(parts) if parts else f"# {path}\n\nNo content available."

    async def mark_dirty(self, entity_id: uuid.UUID) -> None:
        await self._repo.mark_dirty(entity_id)

    async def create_entity_node(self, entity_id: uuid.UUID, entity_type_slug: str, entity_name: str):
        """Auto-create tree node for new entity."""
        path = f"{entity_type_slug}/{entity_name.lower().replace(' ', '-')}"
        return await self._repo.upsert_node(
            workspace_id=self._workspace_id,
            path=path,
            node_type="entity",
            entity_id=entity_id,
        )


def _max_tier_rank(allowed_tiers: set[str]) -> int:
    return max((_TIER_RANK[tier] for tier in allowed_tiers if tier in _TIER_RANK), default=0)


def _claim_field(claim, field: str):
    if isinstance(claim, Mapping):
        return claim[field]
    return getattr(claim, field)
