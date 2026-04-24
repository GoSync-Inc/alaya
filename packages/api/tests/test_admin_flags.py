"""Tests for admin feature flag visibility."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from alayaos_api.deps import get_api_key, get_session
from alayaos_api.main import create_app
from alayaos_core import config
from alayaos_core.models.api_key import APIKey

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
WS_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_api_key(*, scopes: list[str] | None = None, is_bootstrap: bool) -> APIKey:
    return APIKey(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        name="Test Key",
        key_prefix=PREFIX,
        key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        scopes=scopes or ["read", "write", "admin"],
        revoked_at=None,
        expires_at=None,
        is_bootstrap=is_bootstrap,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_app(api_key: APIKey):
    app = create_app()

    async def override_session() -> AsyncGenerator[AsyncMock]:
        yield AsyncMock()

    async def override_api_key() -> APIKey:
        return api_key

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    return app


def test_admin_flags_requires_bootstrap_admin(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_PART_OF_STRICT", "warn")
    config.get_settings.cache_clear()

    app = make_app(make_api_key(is_bootstrap=False))
    client = TestClient(app)
    response = client.get("/admin/flags", headers={"X-Api-Key": RAW_KEY})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.bootstrap_required"

    config.get_settings.cache_clear()


def test_admin_flags_returns_non_default_shape(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_PART_OF_STRICT", "warn")
    config.get_settings.cache_clear()

    app = make_app(make_api_key(is_bootstrap=True))
    client = TestClient(app)
    response = client.get("/admin/flags", headers={"X-Api-Key": RAW_KEY})

    assert response.status_code == 200
    body = response.json()
    flag = body["data"]["ALAYA_PART_OF_STRICT"]

    assert flag == {
        "value": "warn",
        "default": "strict",
        "non_default": True,
        "violations_last_24h": None,
        "violations_last_24h_reason": "counter_not_yet_instrumented",
    }
    assert body["meta"]["flags_non_default"] == 1

    config.get_settings.cache_clear()
