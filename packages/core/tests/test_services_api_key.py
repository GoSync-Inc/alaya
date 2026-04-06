"""Tests for API key service: generate_raw_key, create_api_key, verify_api_key."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
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


# ─── verify_api_key ───────────────────────────────────────────────────────────


class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_returns_none_if_not_starting_with_ak(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        session = AsyncMock()
        result = await verify_api_key(session, "invalid_key_123456")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_too_short(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        session = AsyncMock()
        result = await verify_api_key(session, "ak_short")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_key_not_found(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=None)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, "ak_validprefix12345678")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_hash_mismatch(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        raw_key = "ak_validprefix12345678901234567890"
        wrong_hash_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix=raw_key[:12],
            key_hash="wrong_hash",
            scopes=["read"],
            revoked_at=None,
            expires_at=None,
        )
        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=wrong_hash_key)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_revoked(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        raw_key = "ak_validprefix12345678901234567890"
        correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        revoked_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix=raw_key[:12],
            key_hash=correct_hash,
            scopes=["read"],
            revoked_at=datetime.now(UTC),
            expires_at=None,
        )
        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=revoked_key)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_expired(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        raw_key = "ak_validprefix12345678901234567890"
        correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        expired_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix=raw_key[:12],
            key_hash=correct_hash,
            scopes=["read"],
            revoked_at=None,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=expired_key)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_key_if_valid(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        raw_key = "ak_validprefix12345678901234567890"
        correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        valid_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix=raw_key[:12],
            key_hash=correct_hash,
            scopes=["read"],
            revoked_at=None,
            expires_at=None,
        )
        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=valid_key)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, raw_key)

        assert result is valid_key

    @pytest.mark.asyncio
    async def test_returns_key_if_valid_not_expired(self) -> None:
        from alayaos_core.services.api_key import verify_api_key

        raw_key = "ak_validprefix12345678901234567890"
        correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        future_expiry = datetime.now(UTC) + timedelta(days=30)
        valid_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix=raw_key[:12],
            key_hash=correct_hash,
            scopes=["read"],
            revoked_at=None,
            expires_at=future_expiry,
        )
        session = AsyncMock()
        with patch("alayaos_core.services.api_key.APIKeyRepository") as mock_repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_prefix = AsyncMock(return_value=valid_key)
            mock_repo_cls.return_value = repo_inst

            result = await verify_api_key(session, raw_key)

        assert result is valid_key
