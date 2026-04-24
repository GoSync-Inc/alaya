"""ACL regression tests for TreeService non-admin rendering."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.schemas.tree import TreeNodeView


@pytest.mark.asyncio
async def test_non_admin_get_node_uses_live_filtered_view_without_summary_or_cache_mutation():
    from alayaos_core.services.tree import TreeService

    workspace_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    cached_markdown = "# Cached\n\nrestricted roadmap text"
    cached_summary = {"summary": "restricted roadmap text"}
    node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people/alice",
        workspace_id=workspace_id,
        entity_id=entity_id,
        node_type="entity",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache=cached_markdown,
        summary=cached_summary,
    )

    svc = TreeService(MagicMock(), workspace_id, llm=None)
    svc._repo.get_by_path = AsyncMock(return_value=node)
    svc._entity_visible = AsyncMock(return_value=True)
    svc._load_entity = AsyncMock(return_value=SimpleNamespace(name="Alice", description=None))
    svc._get_filtered_claims = AsyncMock(
        return_value=[SimpleNamespace(predicate="status", value="public launch approved")]
    )

    view = await svc.get_node("people/alice", allowed_tiers={"public", "channel"})

    assert isinstance(view, TreeNodeView)
    assert view.summary is None
    assert view.markdown_cache is not None
    assert "public launch approved" in view.markdown_cache
    assert "restricted roadmap text" not in view.markdown_cache
    assert node.markdown_cache == cached_markdown
    assert node.summary == cached_summary


@pytest.mark.asyncio
async def test_non_admin_get_node_masks_entity_description_in_live_filtered_view():
    from alayaos_core.services.tree import TreeService

    workspace_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people/alice",
        workspace_id=workspace_id,
        entity_id=entity_id,
        node_type="entity",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache="# Cached\n\nrestricted acquisition narrative",
        summary={"summary": "restricted acquisition narrative"},
    )

    svc = TreeService(MagicMock(), workspace_id, llm=None)
    svc._repo.get_by_path = AsyncMock(return_value=node)
    svc._entity_visible = AsyncMock(return_value=True)
    svc._load_entity = AsyncMock(
        return_value=SimpleNamespace(name="Alice", description="restricted acquisition narrative")
    )
    svc._get_filtered_claims = AsyncMock(return_value=[SimpleNamespace(predicate="status", value="public")])

    view = await svc.get_node("people/alice", allowed_tiers={"public", "channel"})

    assert view is not None
    assert view.markdown_cache is not None
    assert "restricted acquisition narrative" not in view.markdown_cache
    assert "- **status**: public" in view.markdown_cache


@pytest.mark.asyncio
async def test_non_admin_export_subtree_uses_filtered_node_views_not_cached_markdown():
    from alayaos_core.services.tree import TreeService

    workspace_id = uuid.uuid4()
    root_node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people",
        workspace_id=workspace_id,
        entity_id=None,
        node_type="index",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache="# Cached root\n\nrestricted root text",
        summary={"summary": "restricted root text"},
    )
    child_node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people/alice",
        workspace_id=workspace_id,
        entity_id=uuid.uuid4(),
        node_type="entity",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache="# Cached child\n\nrestricted child text",
        summary={"summary": "restricted child text"},
    )
    root_view = TreeNodeView(
        id=root_node.id,
        path=root_node.path,
        workspace_id=workspace_id,
        entity_id=None,
        node_type="index",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache="# people",
        summary=None,
    )
    child_view = TreeNodeView(
        id=child_node.id,
        path=child_node.path,
        workspace_id=workspace_id,
        entity_id=child_node.entity_id,
        node_type="entity",
        is_dirty=False,
        last_rebuilt_at=None,
        markdown_cache="# Alice\n\n## Claims\n- **status**: public launch approved",
        summary=None,
    )

    svc = TreeService(MagicMock(), workspace_id, llm=None)
    svc._repo.get_by_path = AsyncMock(return_value=root_node)
    svc._repo.get_children = AsyncMock(return_value=[child_node])
    svc.get_node = AsyncMock(side_effect=[root_view, child_view])

    markdown = await svc.export_subtree("people", allowed_tiers={"public", "channel"})

    assert "public launch approved" in markdown
    assert "restricted root text" not in markdown
    assert "restricted child text" not in markdown
    assert markdown.count("---") == 1
    assert svc.get_node.await_count == 2
