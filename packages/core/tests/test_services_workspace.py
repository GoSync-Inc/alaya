"""Tests for workspace service — create_workspace seeds core types and predicates."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.models.workspace import Workspace
from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES


class TestCreateWorkspace:
    @pytest.mark.asyncio
    async def test_create_workspace_returns_workspace(self) -> None:
        from alayaos_core.services.workspace import create_workspace

        ws = Workspace(id=uuid.uuid4(), name="Demo", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()

        with (
            patch("alayaos_core.services.workspace.WorkspaceRepository") as mock_ws_repo_cls,
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_repo_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_repo_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.create = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            et_repo_inst = AsyncMock()
            et_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_et_repo_cls.return_value = et_repo_inst

            pred_repo_inst = AsyncMock()
            pred_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_pred_repo_cls.return_value = pred_repo_inst

            result = await create_workspace(session, name="Demo", slug="demo")

        assert result is ws

    @pytest.mark.asyncio
    async def test_create_workspace_calls_ws_repo_create(self) -> None:
        from alayaos_core.services.workspace import create_workspace

        ws = Workspace(id=uuid.uuid4(), name="Demo", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()

        with (
            patch("alayaos_core.services.workspace.WorkspaceRepository") as mock_ws_repo_cls,
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_repo_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_repo_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.create = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            et_repo_inst = AsyncMock()
            et_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_et_repo_cls.return_value = et_repo_inst

            pred_repo_inst = AsyncMock()
            pred_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_pred_repo_cls.return_value = pred_repo_inst

            await create_workspace(session, name="Demo", slug="demo", settings={"theme": "dark"})

        ws_repo_inst.create.assert_called_once_with(name="Demo", slug="demo", settings={"theme": "dark"})

    @pytest.mark.asyncio
    async def test_create_workspace_seeds_all_entity_types(self) -> None:
        from alayaos_core.services.workspace import create_workspace

        ws = Workspace(id=uuid.uuid4(), name="Demo", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()

        with (
            patch("alayaos_core.services.workspace.WorkspaceRepository") as mock_ws_repo_cls,
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_repo_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_repo_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.create = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            et_repo_inst = AsyncMock()
            et_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_et_repo_cls.return_value = et_repo_inst

            pred_repo_inst = AsyncMock()
            pred_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_pred_repo_cls.return_value = pred_repo_inst

            await create_workspace(session, name="Demo", slug="demo")

        assert et_repo_inst.upsert_core.call_count == len(CORE_ENTITY_TYPES)

    @pytest.mark.asyncio
    async def test_create_workspace_seeds_all_predicates(self) -> None:
        from alayaos_core.services.workspace import create_workspace

        ws = Workspace(id=uuid.uuid4(), name="Demo", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()

        with (
            patch("alayaos_core.services.workspace.WorkspaceRepository") as mock_ws_repo_cls,
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_repo_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_repo_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.create = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            et_repo_inst = AsyncMock()
            et_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_et_repo_cls.return_value = et_repo_inst

            pred_repo_inst = AsyncMock()
            pred_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_pred_repo_cls.return_value = pred_repo_inst

            await create_workspace(session, name="Demo", slug="demo")

        assert pred_repo_inst.upsert_core.call_count == len(CORE_PREDICATES)

    @pytest.mark.asyncio
    async def test_create_workspace_flushes_after_workspace_create(self) -> None:
        from alayaos_core.services.workspace import create_workspace

        ws = Workspace(id=uuid.uuid4(), name="Demo", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()

        with (
            patch("alayaos_core.services.workspace.WorkspaceRepository") as mock_ws_repo_cls,
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_repo_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_repo_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.create = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            et_repo_inst = AsyncMock()
            et_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_et_repo_cls.return_value = et_repo_inst

            pred_repo_inst = AsyncMock()
            pred_repo_inst.upsert_core = AsyncMock(return_value=MagicMock())
            mock_pred_repo_cls.return_value = pred_repo_inst

            await create_workspace(session, name="Demo", slug="demo")

        session.flush.assert_called()

    def test_core_entity_types_count(self) -> None:
        assert len(CORE_ENTITY_TYPES) == 10

    def test_core_predicates_count(self) -> None:
        assert len(CORE_PREDICATES) == 20

    def test_core_predicates_have_supersession_strategy(self) -> None:
        valid_strategies = {"latest_wins", "explicit_only", "accumulate"}
        for pred in CORE_PREDICATES:
            assert "supersession_strategy" in pred, f"Missing supersession_strategy in {pred['slug']}"
            assert pred["supersession_strategy"] in valid_strategies, f"Invalid strategy in {pred['slug']}"
