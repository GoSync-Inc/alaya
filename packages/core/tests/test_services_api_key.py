"""Tests for API key service: generate_raw_key, create_api_key."""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.models.api_key import APIKey
from alayaos_core.services.api_key import generate_raw_key

# ─── generate_raw_key ─────────────────────────────────────────────────────────


def test_generate_raw_key_starts_with_ak() -> None:
    raw, _prefix, _key_hash = generate_raw_key()
    assert raw.startswith("ak_")


def test_generate_raw_key_prefix_is_first_12_chars() -> None:
    raw, prefix, _key_hash = generate_raw_key()
    assert prefix == raw[:12]
    assert len(prefix) == 12


def test_generate_raw_key_hash_matches_sha256() -> None:
    raw, _prefix, key_hash = generate_raw_key()
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert key_hash == expected


def test_generate_raw_key_unique_each_call() -> None:
    raw1, _, _ = generate_raw_key()
    raw2, _, _ = generate_raw_key()
    assert raw1 != raw2


# ─── create_api_key ───────────────────────────────────────────────────────────


class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_returns_tuple_of_key_and_raw(self) -> None:
        from alayaos_core.services.api_key import create_api_key

        ws_id = uuid.uuid4()
        session = AsyncMock()

        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            api_key_obj = APIKey(
                id=uuid.uuid4(),
                workspace_id=ws_id,
                name="Test Key",
                key_prefix="ak_testprefix",
                key_hash="somehash",
                scopes=["read", "write"],
            )
            repo_inst.create = AsyncMock(return_value=api_key_obj)
            mock_repo_cls.return_value = repo_inst

            result_key, raw_key = await create_api_key(session, workspace_id=ws_id, name="Test Key")

        assert result_key is api_key_obj
        assert isinstance(raw_key, str)
        assert raw_key.startswith("ak_")

    @pytest.mark.asyncio
    async def test_default_scopes(self) -> None:
        from alayaos_core.services.api_key import create_api_key

        ws_id = uuid.uuid4()
        session = AsyncMock()

        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.create = AsyncMock(return_value=MagicMock())
            mock_repo_cls.return_value = repo_inst

            await create_api_key(session, workspace_id=ws_id, name="Key")

        call_kwargs = repo_inst.create.call_args.kwargs
        assert call_kwargs["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_custom_scopes(self) -> None:
        from alayaos_core.services.api_key import create_api_key

        ws_id = uuid.uuid4()
        session = AsyncMock()

        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.create = AsyncMock(return_value=MagicMock())
            mock_repo_cls.return_value = repo_inst

            await create_api_key(session, workspace_id=ws_id, name="Key", scopes=["read", "admin"])

        call_kwargs = repo_inst.create.call_args.kwargs
        assert call_kwargs["scopes"] == ["read", "admin"]

    @pytest.mark.asyncio
    async def test_bootstrap_flag(self) -> None:
        from alayaos_core.services.api_key import create_api_key

        ws_id = uuid.uuid4()
        session = AsyncMock()

        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.create = AsyncMock(return_value=MagicMock())
            mock_repo_cls.return_value = repo_inst

            await create_api_key(session, workspace_id=ws_id, name="Bootstrap", is_bootstrap=True)

        call_kwargs = repo_inst.create.call_args.kwargs
        assert call_kwargs["is_bootstrap"] is True
