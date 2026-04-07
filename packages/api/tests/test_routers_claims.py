"""Tests for the claims router."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
WS_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_api_key(scopes=None) -> APIKey:
    import hashlib

    return APIKey(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        name="Test Key",
        key_prefix=PREFIX,
        key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        scopes=scopes or ["read", "write", "admin"],
        revoked_at=None,
        expires_at=None,
        is_bootstrap=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_app_with_mock_session(api_key: APIKey):
    app = create_app()

    async def override_session():
        session = AsyncMock()
        yield session

    async def override_api_key():
        return api_key

    async def override_workspace_session():
        session = AsyncMock()
        yield session

    from alayaos_api.deps import get_api_key, get_session, get_workspace_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    return app


def make_claim(ws_id: uuid.UUID | None = None, entity_id: uuid.UUID | None = None):
    from alayaos_core.models.claim import L2Claim

    now = datetime.now(UTC)
    claim = L2Claim(
        id=uuid.uuid4(),
        workspace_id=ws_id or WS_ID,
        entity_id=entity_id or uuid.uuid4(),
        predicate="status",
        predicate_id=None,
        value={"v": "active"},
        confidence=0.9,
        status="active",
        value_type="text",
        observed_at=None,
        valid_from=None,
        valid_to=None,
        supersedes=None,
        source_event_id=None,
        source_summary=None,
        extraction_run_id=None,
    )
    claim.created_at = now
    claim.updated_at = now
    return claim


class TestClaimsRouter:
    def test_list_claims_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        claim = make_claim()

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([claim], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/claims", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "pagination" in body

    def test_list_claims_with_filters(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        entity_id = uuid.uuid4()
        claim = make_claim(entity_id=entity_id)

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([claim], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/claims?entity_id={entity_id}&predicate=status&status=active",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200

    def test_get_claim_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        claim = make_claim()

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=claim)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/claims/{claim.id}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["data"]["predicate"] == "status"

    def test_get_claim_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/claims/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_update_claim_status_valid_transition(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        claim = make_claim()
        retracted = make_claim()
        retracted.status = "retracted"

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=claim)
            repo.update_status = AsyncMock(return_value=retracted)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.patch(
                f"/api/v1/claims/{claim.id}",
                json={"status": "retracted"},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "retracted"

    def test_update_claim_status_invalid_transition_returns_422(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        claim = make_claim()

        with patch("alayaos_api.routers.claims.ClaimRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=claim)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.patch(
                f"/api/v1/claims/{claim.id}",
                json={"status": "invalid_status"},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 422
