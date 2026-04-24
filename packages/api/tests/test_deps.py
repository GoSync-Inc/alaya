"""Tests for dependency injection: get_api_key, require_scope, response helpers."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

from alayaos_api.deps import data_response, paginated_response
from alayaos_core.models.api_key import APIKey

# ─── data_response / paginated_response helpers ───────────────────────────────


def test_data_response_wraps_data() -> None:
    result = data_response({"id": 1})
    assert result == {"data": {"id": 1}}


def test_paginated_response_structure() -> None:
    from pydantic import BaseModel

    class Item(BaseModel):
        id: int

        class Config:
            from_attributes = True

    class FakeObj:
        id = 1

    result = paginated_response([FakeObj()], Item, "cursor123", True)
    assert result["data"][0] == Item(id=1)
    assert result["pagination"]["next_cursor"] == "cursor123"
    assert result["pagination"]["has_more"] is True
    assert result["pagination"]["count"] == 1
    assert result["meta"] == {"filtered_count": 0, "filter_reason": None}


def test_paginated_response_populates_filter_reason_only_when_filtered() -> None:
    from pydantic import BaseModel

    class Item(BaseModel):
        id: int

        class Config:
            from_attributes = True

    class FakeObj:
        id = 1

    result = paginated_response(
        [FakeObj()],
        Item,
        None,
        False,
        filtered_count=3,
        filter_reason="access_level",
    )
    assert result["meta"] == {"filtered_count": 3, "filter_reason": "access_level"}

    unfiltered = paginated_response(
        [FakeObj()],
        Item,
        None,
        False,
        filtered_count=0,
        filter_reason="access_level",
    )
    assert unfiltered["meta"] == {"filtered_count": 0, "filter_reason": None}


def test_compute_allowed_levels_maps_scopes_and_fails_closed() -> None:
    from alayaos_api.deps import _compute_allowed_levels

    assert _compute_allowed_levels(["read"]) == {"public", "channel"}
    assert _compute_allowed_levels(["write"]) == {"public", "channel", "private"}
    assert _compute_allowed_levels(["admin"]) == {"public", "channel", "private", "restricted"}
    assert _compute_allowed_levels(["unknown"]) == {"public"}
    assert _compute_allowed_levels(["read", "admin", "unknown"]) == {
        "public",
        "channel",
        "private",
        "restricted",
    }


# ─── Auth dependency via HTTP endpoint ────────────────────────────────────────


def _make_auth_app(valid_key: APIKey | None = None):
    """Create a minimal FastAPI app that uses get_api_key dependency."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(request):

        # Not using real DI here — just test the function directly
        return {"ok": True}

    return app


def _valid_api_key(scopes=None) -> tuple[APIKey, str]:
    """Create a valid APIKey model and raw key pair for testing."""
    raw_key = "ak_testprefix12345678901234567890"
    prefix = raw_key[:12]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    ws_id = uuid.uuid4()
    key = APIKey(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        name="Test Key",
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes or ["read", "write", "admin"],
        revoked_at=None,
        expires_at=None,
        is_bootstrap=False,
    )
    return key, raw_key


@pytest.mark.asyncio
async def test_get_api_key_missing_header_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    session = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_api_key(session=session, x_api_key="")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.missing_key"


@pytest.mark.asyncio
async def test_get_api_key_malformed_no_ak_prefix_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    session = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_api_key(session=session, x_api_key="invalid_prefix_123456789")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.malformed_key"


@pytest.mark.asyncio
async def test_get_api_key_too_short_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    session = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_api_key(session=session, x_api_key="ak_short")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.malformed_key"


@pytest.mark.asyncio
async def test_get_api_key_not_found_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    session = AsyncMock()
    with patch("alayaos_api.deps.APIKeyRepository") as mock_cls:
        repo = AsyncMock()
        repo.get_by_prefix = AsyncMock(return_value=None)
        mock_cls.return_value = repo
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key(session=session, x_api_key="ak_validprefix12345678")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.invalid_key"


@pytest.mark.asyncio
async def test_get_api_key_revoked_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    valid_key, raw_key = _valid_api_key()
    valid_key.revoked_at = datetime.now(UTC)

    session = AsyncMock()
    with patch("alayaos_api.deps.APIKeyRepository") as mock_cls:
        repo = AsyncMock()
        repo.get_by_prefix = AsyncMock(return_value=valid_key)
        mock_cls.return_value = repo
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key(session=session, x_api_key=raw_key)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.invalid_key"


@pytest.mark.asyncio
async def test_get_api_key_expired_raises_401() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import get_api_key

    valid_key, raw_key = _valid_api_key()
    valid_key.expires_at = datetime.now(UTC) - timedelta(hours=1)

    session = AsyncMock()
    with patch("alayaos_api.deps.APIKeyRepository") as mock_cls:
        repo = AsyncMock()
        repo.get_by_prefix = AsyncMock(return_value=valid_key)
        mock_cls.return_value = repo
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key(session=session, x_api_key=raw_key)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "auth.expired_key"


@pytest.mark.asyncio
async def test_get_api_key_valid_returns_key() -> None:
    from alayaos_api.deps import get_api_key

    valid_key, raw_key = _valid_api_key()

    session = AsyncMock()
    with patch("alayaos_api.deps.APIKeyRepository") as mock_cls:
        repo = AsyncMock()
        repo.get_by_prefix = AsyncMock(return_value=valid_key)
        mock_cls.return_value = repo
        result = await get_api_key(session=session, x_api_key=raw_key)
    assert result is valid_key


@pytest.mark.asyncio
async def test_require_scope_passes_when_scope_present() -> None:
    from alayaos_api.deps import require_scope

    valid_key, _ = _valid_api_key(scopes=["read", "write", "admin"])
    checker = require_scope("write")
    result = await checker(api_key=valid_key)
    assert result is valid_key


@pytest.mark.asyncio
async def test_require_scope_allows_write_and_admin_to_read() -> None:
    from alayaos_api.deps import require_scope

    write_key, _ = _valid_api_key(scopes=["write"])
    admin_key, _ = _valid_api_key(scopes=["admin"])
    checker = require_scope("read")

    assert await checker(api_key=write_key) is write_key
    assert await checker(api_key=admin_key) is admin_key


@pytest.mark.asyncio
async def test_require_scope_does_not_allow_read_to_write_or_admin() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import require_scope

    read_key, _ = _valid_api_key(scopes=["read"])

    with pytest.raises(HTTPException):
        await require_scope("write")(api_key=read_key)

    with pytest.raises(HTTPException):
        await require_scope("admin")(api_key=read_key)


@pytest.mark.asyncio
async def test_require_scope_raises_403_when_missing() -> None:
    from fastapi import HTTPException

    from alayaos_api.deps import require_scope

    valid_key, _ = _valid_api_key(scopes=["read"])
    checker = require_scope("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(api_key=valid_key)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"]["code"] == "auth.insufficient_scope"


@pytest.mark.asyncio
async def test_workspace_session_sets_bound_request_context_gucs() -> None:
    """Workspace context must use bound set_config params, not interpolated SET LOCAL SQL."""
    from alayaos_api.deps import get_workspace_session

    valid_key, _raw_key = _valid_api_key(scopes=["write"])

    session = AsyncMock()
    session.execute = AsyncMock()

    with patch("alayaos_api.deps.bind_contextvars") as mock_bind:
        gen = get_workspace_session(session=session, api_key=valid_key)
        await gen.__anext__()

    call_args = session.execute.call_args
    assert call_args is not None
    sql_text = str(call_args.args[0])
    params = call_args.args[1]
    assert "set_config('app.workspace_id', :wid, true)" in sql_text
    assert "set_config('app.allowed_access_levels', :allowed, true)" in sql_text
    assert "set_config('hnsw.iterative_scan', 'strict_order', true)" in sql_text
    assert "SET LOCAL" not in sql_text
    assert params == {
        "wid": str(valid_key.workspace_id),
        "allowed": "channel,private,public",
    }
    mock_bind.assert_called_once_with(
        workspace_id=str(valid_key.workspace_id),
        allowed_access_levels="channel,private,public",
    )


@pytest.mark.asyncio
async def test_set_local_rejects_malicious_workspace_id() -> None:
    """Regression: malicious workspace_id triggers ValueError from uuid.UUID()."""
    from alayaos_api.deps import get_workspace_session

    valid_key, _raw_key = _valid_api_key()
    # Inject a malicious value that is NOT a valid UUID
    valid_key.workspace_id = "'; DROP TABLE workspaces; --"

    session = AsyncMock()

    gen = get_workspace_session(session=session, api_key=valid_key)
    with pytest.raises(ValueError):
        await gen.__anext__()
