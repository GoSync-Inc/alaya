"""Tests for docker/seed.py idempotent seed logic."""

import importlib.util
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.models.api_key import APIKey
from alayaos_core.models.workspace import Workspace

# Load seed module from docker/seed.py using importlib to avoid name conflict with 'docker' package
_WORKTREE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_SEED_PATH = os.path.join(_WORKTREE_ROOT, "docker", "seed.py")
_spec = importlib.util.spec_from_file_location("docker_seed", _SEED_PATH)
assert _spec is not None
_seed_module = importlib.util.module_from_spec(_spec)
sys.modules["docker_seed"] = _seed_module
assert _spec.loader is not None
_spec.loader.exec_module(_seed_module)  # type: ignore[union-attr]
seed = _seed_module.seed

_MODULE = "docker_seed"


class TestSeedFunction:
    @pytest.mark.asyncio
    async def test_seed_creates_workspace_when_not_exists(self) -> None:
        """seed() creates demo workspace when it doesn't exist."""
        ws = Workspace(id=uuid.uuid4(), name="Demo Workspace", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch(f"{_MODULE}.WorkspaceRepository") as mock_ws_repo_cls,
            patch(f"{_MODULE}.APIKeyRepository") as mock_api_key_repo_cls,
            patch(f"{_MODULE}.create_workspace") as mock_create_ws,
            patch(f"{_MODULE}.create_api_key") as mock_create_key,
            patch(f"{_MODULE}.Settings") as mock_settings_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.get_by_slug = AsyncMock(return_value=None)
            mock_ws_repo_cls.return_value = ws_repo_inst

            mock_create_ws.return_value = ws

            api_key_repo_inst = AsyncMock()
            mock_api_key = APIKey(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                name="Bootstrap Key",
                key_prefix="ak_bootstrap",
                key_hash="hash",
                scopes=["read", "write", "admin"],
                is_bootstrap=True,
            )
            api_key_repo_inst.list = AsyncMock(return_value=([], None, False))
            mock_api_key_repo_cls.return_value = api_key_repo_inst

            mock_create_key.return_value = (mock_api_key, "ak_rawkeyvalue")

            settings_inst = MagicMock()
            settings_inst.ENV = "dev"
            mock_settings_cls.return_value = settings_inst

            await seed(session)

        mock_create_ws.assert_called_once_with(session, name="Demo Workspace", slug="demo")
        session.flush.assert_called()

    @pytest.mark.asyncio
    async def test_seed_skips_workspace_creation_when_exists(self) -> None:
        """seed() skips workspace creation when it already exists."""
        ws = Workspace(id=uuid.uuid4(), name="Demo Workspace", slug="demo", settings={})
        session = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch(f"{_MODULE}.WorkspaceRepository") as mock_ws_repo_cls,
            patch(f"{_MODULE}.APIKeyRepository") as mock_api_key_repo_cls,
            patch(f"{_MODULE}.create_workspace") as mock_create_ws,
            patch(f"{_MODULE}.create_api_key") as mock_create_key,
            patch(f"{_MODULE}.Settings") as mock_settings_cls,
            patch(f"{_MODULE}.seed_core_metadata", new_callable=AsyncMock),
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.get_by_slug = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            api_key_repo_inst = AsyncMock()
            api_key_repo_inst.list = AsyncMock(return_value=([], None, False))
            mock_api_key_repo_cls.return_value = api_key_repo_inst

            mock_create_key.return_value = (MagicMock(), "ak_raw")

            settings_inst = MagicMock()
            settings_inst.ENV = "dev"
            mock_settings_cls.return_value = settings_inst

            await seed(session)

        mock_create_ws.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_creates_bootstrap_key_when_not_exists(self) -> None:
        """seed() creates bootstrap API key when none exists."""
        ws = Workspace(id=uuid.uuid4(), name="Demo Workspace", slug="demo", settings={})
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch(f"{_MODULE}.WorkspaceRepository") as mock_ws_repo_cls,
            patch(f"{_MODULE}.APIKeyRepository") as mock_api_key_repo_cls,
            patch(f"{_MODULE}.create_workspace") as mock_create_ws,
            patch(f"{_MODULE}.create_api_key") as mock_create_key,
            patch(f"{_MODULE}.Settings") as mock_settings_cls,
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.get_by_slug = AsyncMock(return_value=None)
            mock_ws_repo_cls.return_value = ws_repo_inst
            mock_create_ws.return_value = ws

            api_key_repo_inst = AsyncMock()
            api_key_repo_inst.list = AsyncMock(return_value=([], None, False))
            mock_api_key_repo_cls.return_value = api_key_repo_inst

            mock_api_key = MagicMock()
            mock_create_key.return_value = (mock_api_key, "ak_bootstrap_raw_key")

            settings_inst = MagicMock()
            settings_inst.ENV = "dev"
            mock_settings_cls.return_value = settings_inst

            await seed(session)

        mock_create_key.assert_called_once()
        call_kwargs = mock_create_key.call_args
        assert call_kwargs.kwargs.get("is_bootstrap") is True
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_skips_bootstrap_key_when_exists(self) -> None:
        """seed() skips bootstrap key creation when one already exists."""
        ws = Workspace(id=uuid.uuid4(), name="Demo Workspace", slug="demo", settings={})
        existing_bootstrap = APIKey(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            name="Bootstrap Key",
            key_prefix="ak_existing123",
            key_hash="hash",
            scopes=["read"],
            is_bootstrap=True,
        )
        session = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch(f"{_MODULE}.WorkspaceRepository") as mock_ws_repo_cls,
            patch(f"{_MODULE}.APIKeyRepository") as mock_api_key_repo_cls,
            patch(f"{_MODULE}.create_workspace"),
            patch(f"{_MODULE}.create_api_key") as mock_create_key,
            patch(f"{_MODULE}.Settings") as mock_settings_cls,
            patch(f"{_MODULE}.seed_core_metadata", new_callable=AsyncMock),
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.get_by_slug = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            api_key_repo_inst = AsyncMock()
            api_key_repo_inst.list = AsyncMock(return_value=([existing_bootstrap], None, False))
            mock_api_key_repo_cls.return_value = api_key_repo_inst

            settings_inst = MagicMock()
            settings_inst.ENV = "dev"
            mock_settings_cls.return_value = settings_inst

            await seed(session)

        mock_create_key.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_skips_bootstrap_key_in_production(self) -> None:
        """seed() skips bootstrap key in production mode."""
        ws = Workspace(id=uuid.uuid4(), name="Demo Workspace", slug="demo", settings={})
        session = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch(f"{_MODULE}.WorkspaceRepository") as mock_ws_repo_cls,
            patch(f"{_MODULE}.APIKeyRepository") as mock_api_key_repo_cls,
            patch(f"{_MODULE}.create_workspace"),
            patch(f"{_MODULE}.create_api_key") as mock_create_key,
            patch(f"{_MODULE}.Settings") as mock_settings_cls,
            patch(f"{_MODULE}.seed_core_metadata", new_callable=AsyncMock),
        ):
            ws_repo_inst = AsyncMock()
            ws_repo_inst.get_by_slug = AsyncMock(return_value=ws)
            mock_ws_repo_cls.return_value = ws_repo_inst

            api_key_repo_inst = AsyncMock()
            mock_api_key_repo_cls.return_value = api_key_repo_inst

            settings_inst = MagicMock()
            settings_inst.ENV = "production"
            mock_settings_cls.return_value = settings_inst

            await seed(session)

        mock_create_key.assert_not_called()
        # In production, we return early so no commit
        api_key_repo_inst.list.assert_not_called()
