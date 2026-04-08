"""Knowledge tree service — briefing synthesis with dirty-flag rebuild."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from alayaos_core.repositories.tree import TreeNodeRepository
from alayaos_core.schemas.tree import TreeBriefing

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.llm.interface import LLMServiceInterface

log = structlog.get_logger()

BRIEFING_TIMEOUT = 6  # seconds


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

    async def get_node(self, path: str):
        """Get a tree node, rebuilding briefing if dirty."""
        node = await self._repo.get_by_path(path)
        if node and node.is_dirty and self._llm:
            await self._rebuild_briefing(node)
        return node

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
    def _render_raw_claims_markdown(entity, claims) -> str:
        lines = [f"# {entity.name}", ""]
        if entity.description:
            lines.extend([entity.description, ""])
        lines.append("## Claims")
        for c in claims:
            lines.append(f"- **{c.predicate}**: {c.value}")
        return "\n".join(lines)

    async def export_subtree(self, path: str) -> str:
        """Export subtree as markdown."""
        nodes = await self._repo.get_children(path, depth=99)
        root_node = await self._repo.get_by_path(path)

        parts = []
        if root_node and root_node.markdown_cache:
            parts.append(root_node.markdown_cache)

        for node in nodes:
            if node.markdown_cache:
                parts.append(node.markdown_cache)
            else:
                parts.append(f"## {node.path}")

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
