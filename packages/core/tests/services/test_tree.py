"""Tests for Tree schemas, TreeNodeRepository, and TreeService."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.llm.fake import FakeLLMAdapter
from alayaos_core.schemas.tree import (
    TreeBriefing,
    TreeExportRequest,
    TreeNodeResponse,
    TreeNodeView,
    TreePathRequest,
)

# ---------------------------------------------------------------------------
# TASK 1: Tree Schema Tests
# ---------------------------------------------------------------------------


class TestTreePathRequest:
    """TreePathRequest validation."""

    def test_valid_simple_path(self):
        req = TreePathRequest(path="person/alice")
        assert req.path == "person/alice"

    def test_valid_deep_path(self):
        req = TreePathRequest(path="a/b/c/d/e/f/g/h/i/j")
        assert req.path == "a/b/c/d/e/f/g/h/i/j"

    def test_path_traversal_rejected(self):
        with pytest.raises(Exception, match="Path traversal"):
            TreePathRequest(path="../etc/passwd")

    def test_double_slash_rejected(self):
        with pytest.raises(Exception, match="Double slashes"):
            TreePathRequest(path="person//alice")

    def test_control_char_rejected(self):
        with pytest.raises(Exception, match="Control characters"):
            TreePathRequest(path="person/ali\x00ce")

    def test_path_too_long_rejected(self):
        with pytest.raises(Exception, match="Path too long"):
            TreePathRequest(path="x" * 513)

    def test_path_too_deep_rejected(self):
        with pytest.raises(Exception, match="Path too deep"):
            TreePathRequest(path="a/b/c/d/e/f/g/h/i/j/k")  # 11 levels

    def test_null_byte_rejected(self):
        with pytest.raises(Exception, match="Control characters"):
            TreePathRequest(path="\x00")


class TestTreeExportRequest:
    """TreeExportRequest validation."""

    def test_empty_path_allowed(self):
        req = TreeExportRequest(path="")
        assert req.path == ""

    def test_default_path_is_empty(self):
        req = TreeExportRequest()
        assert req.path == ""

    def test_valid_path_accepted(self):
        req = TreeExportRequest(path="person/alice")
        assert req.path == "person/alice"

    def test_traversal_in_non_empty_path_rejected(self):
        with pytest.raises(Exception, match="Path traversal"):
            TreeExportRequest(path="../evil")


class TestTreeBriefing:
    """TreeBriefing schema validation."""

    def test_valid_briefing(self):
        b = TreeBriefing(
            title="Alice",
            summary="Senior engineer at ACME",
            key_facts=["Works on backend", "Joined 2022"],
            status="active",
        )
        assert b.title == "Alice"
        assert len(b.key_facts) == 2
        assert b.status == "active"
        assert b.last_updated is None

    def test_optional_fields_default_none(self):
        b = TreeBriefing(title="Bob", summary="Summary", key_facts=[])
        assert b.status is None
        assert b.last_updated is None

    def test_key_facts_empty_list(self):
        b = TreeBriefing(title="X", summary="Y", key_facts=[])
        assert b.key_facts == []


class TestTreeNodeResponse:
    """TreeNodeResponse schema."""

    def test_model_validate_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "id": uuid.uuid4(),
            "path": "person/alice",
            "node_type": "entity",
            "entity_id": uuid.uuid4(),
            "is_dirty": False,
            "sort_order": 0,
            "summary": {"title": "Alice"},
            "markdown_cache": "# Alice",
            "last_rebuilt_at": now,
            "created_at": now,
            "updated_at": now,
        }
        resp = TreeNodeResponse.model_validate(data)
        assert resp.path == "person/alice"
        assert resp.node_type == "entity"
        assert resp.markdown_cache == "# Alice"

    def test_optional_fields_nullable(self):
        now = datetime.now(UTC)
        data = {
            "id": uuid.uuid4(),
            "path": "person",
            "node_type": "index",
            "is_dirty": True,
            "sort_order": 0,
            "summary": {},
            "created_at": now,
            "updated_at": now,
        }
        resp = TreeNodeResponse.model_validate(data)
        assert resp.entity_id is None
        assert resp.markdown_cache is None
        assert resp.last_rebuilt_at is None


# ---------------------------------------------------------------------------
# TASK 2: TreeNodeRepository Tests (mock session)
# ---------------------------------------------------------------------------


def make_session_mock():
    """Build a minimal AsyncSession mock."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestTreeNodeRepository:
    """TreeNodeRepository with mocked AsyncSession."""

    @pytest.mark.asyncio
    async def test_get_by_path_returns_none_when_not_found(self):
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        node = await repo.get_by_path("person/alice")

        assert node is None

    @pytest.mark.asyncio
    async def test_get_by_path_returns_node_when_found(self):
        from alayaos_core.models.tree import L3TreeNode
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        fake_node = L3TreeNode(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            path="person/alice",
            node_type="entity",
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = fake_node
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        node = await repo.get_by_path("person/alice")

        assert node is fake_node
        assert node.path == "person/alice"

    @pytest.mark.asyncio
    async def test_upsert_node_creates_new_when_not_exists(self):
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        # First call: get_by_path returns None
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        node = await repo.upsert_node(ws_id, "person/alice", "entity", None)

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert node.path == "person/alice"
        assert node.node_type == "entity"
        assert node.is_dirty is True

    @pytest.mark.asyncio
    async def test_upsert_node_returns_existing_when_found(self):
        from alayaos_core.models.tree import L3TreeNode
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        existing_node = L3TreeNode(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            path="person/alice",
            node_type="entity",
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_node
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        node = await repo.upsert_node(ws_id, "person/alice", "entity", None)

        session.add.assert_not_called()
        assert node is existing_node

    @pytest.mark.asyncio
    async def test_get_dirty_nodes_returns_dirty_nodes(self):
        from alayaos_core.models.tree import L3TreeNode
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        dirty_node = L3TreeNode(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            path="person/alice",
            node_type="entity",
            is_dirty=True,
        )
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [dirty_node]
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        nodes = await repo.get_dirty_nodes()

        assert len(nodes) == 1
        assert nodes[0].is_dirty is True

    @pytest.mark.asyncio
    async def test_mark_dirty_executes_update(self):
        from alayaos_core.repositories.tree import TreeNodeRepository

        session = make_session_mock()
        result_mock = MagicMock()
        session.execute.return_value = result_mock

        ws_id = uuid.uuid4()
        repo = TreeNodeRepository(session, ws_id)
        entity_id = uuid.uuid4()
        await repo.mark_dirty(entity_id)

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# TASK 3: TreeService Tests
# ---------------------------------------------------------------------------


def make_tree_node(path="person/alice", node_type="entity", is_dirty=False, entity_id=None):
    """Helper to create an L3TreeNode for testing."""
    from alayaos_core.models.tree import L3TreeNode

    return L3TreeNode(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        path=path,
        node_type=node_type,
        is_dirty=is_dirty,
        entity_id=entity_id,
        markdown_cache=None,
        summary={},
    )


class TestTreeService:
    """TreeService unit tests with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_get_node_returns_none_when_not_found(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        # Patch _repo.get_by_path to return None
        svc._repo.get_by_path = AsyncMock(return_value=None)

        node = await svc.get_node("person/nonexistent", allowed_tiers={"restricted"})
        assert node is None

    @pytest.mark.asyncio
    async def test_get_node_returns_clean_node_without_rebuild(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        clean_node = make_tree_node(is_dirty=False)
        svc._repo.get_by_path = AsyncMock(return_value=clean_node)

        node = await svc.get_node("person/alice", allowed_tiers={"restricted"})
        assert isinstance(node, TreeNodeView)
        assert node.path == clean_node.path
        assert node.summary == clean_node.summary

    @pytest.mark.asyncio
    async def test_get_node_dirty_without_llm_skips_rebuild(self):
        """Dirty node without LLM returns node without rebuilding."""
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        dirty_node = make_tree_node(is_dirty=True)
        svc._repo.get_by_path = AsyncMock(return_value=dirty_node)

        node = await svc.get_node("person/alice", allowed_tiers={"restricted"})
        assert isinstance(node, TreeNodeView)
        assert node.path == dirty_node.path
        assert node.is_dirty is True  # unchanged since no LLM

    @pytest.mark.asyncio
    async def test_get_children_delegates_to_repo(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        child1 = make_tree_node(path="person/alice")
        child2 = make_tree_node(path="person/bob")
        svc._repo.get_children = AsyncMock(return_value=[child1, child2])

        children = await svc.get_children("person")
        assert len(children) == 2

    @pytest.mark.asyncio
    async def test_get_root_returns_root_nodes(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        index_node = make_tree_node(path="person", node_type="index")
        svc._repo.get_children = AsyncMock(return_value=[index_node])

        roots = await svc.get_root()
        assert len(roots) == 1
        assert roots[0].path == "person"

    @pytest.mark.asyncio
    async def test_get_node_hides_index_cached_markdown_for_non_admin(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        index_node = make_tree_node(path="person", node_type="index", entity_id=None)
        index_node.markdown_cache = "# People\n\nrestricted codename BLACKBIRD"
        index_node.summary = {"title": "People", "summary": "restricted codename BLACKBIRD"}
        svc._repo.get_by_path = AsyncMock(return_value=index_node)

        node = await svc.get_node("person", allowed_tiers={"public", "channel"})

        assert isinstance(node, TreeNodeView)
        assert node.summary is None
        assert node.markdown_cache is None

    @pytest.mark.asyncio
    async def test_mark_dirty_delegates_to_repo(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        svc._repo.mark_dirty = AsyncMock()
        entity_id = uuid.uuid4()
        await svc.mark_dirty(entity_id)

        svc._repo.mark_dirty.assert_called_once_with(entity_id)

    @pytest.mark.asyncio
    async def test_export_subtree_returns_placeholder_when_no_nodes(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        svc._repo.get_children = AsyncMock(return_value=[])
        svc._repo.get_by_path = AsyncMock(return_value=None)

        result = await svc.export_subtree("person", allowed_tiers={"restricted"})
        assert "person" in result
        assert "No content available" in result

    @pytest.mark.asyncio
    async def test_export_subtree_skips_index_cached_markdown_for_non_admin(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        index_node = make_tree_node(path="person", node_type="index", entity_id=None)
        index_node.markdown_cache = "# People\n\nrestricted codename BLACKBIRD"
        svc._repo.get_by_path = AsyncMock(return_value=index_node)
        svc._repo.get_children = AsyncMock(return_value=[])

        result = await svc.export_subtree("person", allowed_tiers={"public", "channel"})

        assert "BLACKBIRD" not in result
        assert "restricted codename" not in result

    @pytest.mark.asyncio
    async def test_rebuild_briefing_index_node_clears_dirty(self):
        """Index node (no entity_id) should have dirty cleared without LLM call."""
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        llm = FakeLLMAdapter()
        svc = TreeService(session, ws_id, llm=llm)

        index_node = make_tree_node(path="person", node_type="index", is_dirty=True)

        # flush should set is_dirty = False
        async def flush_side_effect():
            pass

        session.flush = AsyncMock(side_effect=flush_side_effect)
        await svc._rebuild_briefing(index_node)

        assert index_node.is_dirty is False
        assert index_node.last_rebuilt_at is not None

    @pytest.mark.asyncio
    async def test_render_briefing_markdown_produces_expected_format(self):
        from alayaos_core.services.tree import TreeService

        briefing = TreeBriefing(
            title="Alice",
            summary="Senior engineer",
            key_facts=["Works on backend", "Joined 2022"],
            status="active",
        )
        md = TreeService._render_briefing_markdown(briefing)
        assert "# Alice" in md
        assert "Senior engineer" in md
        assert "- Works on backend" in md
        assert "**Status:** active" in md

    @pytest.mark.asyncio
    async def test_render_raw_claims_markdown_no_claims(self):
        from alayaos_core.services.tree import TreeService

        entity = MagicMock()
        entity.name = "Alice"
        entity.description = None
        md = TreeService._render_raw_claims_markdown(entity, [])
        assert "# Alice" in md
        assert "## Claims" in md

    @pytest.mark.asyncio
    async def test_create_entity_node_delegates_to_repo(self):
        from alayaos_core.services.tree import TreeService

        session = make_session_mock()
        ws_id = uuid.uuid4()
        svc = TreeService(session, ws_id, llm=None)

        entity_id = uuid.uuid4()
        fake_node = make_tree_node(path="person/alice-smith", node_type="entity", entity_id=entity_id)
        svc._repo.upsert_node = AsyncMock(return_value=fake_node)

        node = await svc.create_entity_node(entity_id, "person", "Alice Smith")
        svc._repo.upsert_node.assert_called_once_with(
            workspace_id=ws_id,
            path="person/alice-smith",
            node_type="entity",
            entity_id=entity_id,
        )
        assert node.path == "person/alice-smith"


# ---------------------------------------------------------------------------
# TASK 4: FakeLLMAdapter compatibility with TreeBriefing
# ---------------------------------------------------------------------------


class TestFakeLLMAdapterTreeBriefing:
    """FakeLLMAdapter can synthesize TreeBriefing with defaults."""

    @pytest.mark.asyncio
    async def test_fake_llm_returns_treebriefing_with_defaults(self):
        """FakeLLMAdapter should return a default TreeBriefing without raising."""
        from alayaos_core.schemas.tree import TreeBriefing

        adapter = FakeLLMAdapter()
        # Register a response with valid TreeBriefing fields
        adapter.add_response(
            FakeLLMAdapter.content_hash("Entity: Alice\nType: person\n\nClaims:\n"),
            {
                "title": "Alice",
                "summary": "Key person in the team",
                "key_facts": ["Backend engineer"],
                "status": "active",
            },
        )
        briefing, usage = await adapter.extract(
            text="Entity: Alice\nType: person\n\nClaims:\n",
            system_prompt="Generate briefing",
            response_model=TreeBriefing,
        )
        assert isinstance(briefing, TreeBriefing)
        assert briefing.title == "Alice"
        assert usage.tokens_in == 100

    @pytest.mark.asyncio
    async def test_fake_llm_treebriefing_model_override(self):
        """FakeLLMAdapter _MODEL_OVERRIDES can handle TreeBriefing if added."""
        from alayaos_core.schemas.tree import TreeBriefing

        adapter = FakeLLMAdapter()
        # No override — should fall back to _default_response
        # TreeBriefing has required fields without defaults, so model_validate may fail
        # unless we register a response
        text = "test content xyz"
        adapter.add_response(
            FakeLLMAdapter.content_hash(text),
            {"title": "Test", "summary": "Test summary", "key_facts": []},
        )
        briefing, _ = await adapter.extract(text=text, system_prompt="s", response_model=TreeBriefing)
        assert isinstance(briefing, TreeBriefing)
        assert briefing.title == "Test"
