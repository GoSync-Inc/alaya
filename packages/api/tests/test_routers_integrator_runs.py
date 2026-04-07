"""Tests for the integrator-runs router."""

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


def make_integrator_run(ws_id: uuid.UUID | None = None):
    from alayaos_core.models.integrator_run import IntegratorRun

    now = datetime.now(UTC)
    run = IntegratorRun(
        id=uuid.uuid4(),
        workspace_id=ws_id or WS_ID,
        trigger="manual",
        scope_description="test",
        status="running",
    )
    run.started_at = now
    return run


class TestIntegratorRunsRouter:
    def test_list_integrator_runs_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()

        with patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([run], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/integrator-runs", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "pagination" in body

    def test_get_integrator_run_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()

        with patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=run)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/integrator-runs/{run.id}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["trigger"] == "manual"
        assert data["status"] == "running"

    def test_get_integrator_run_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/integrator-runs/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_trigger_integrator_run_returns_202(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()

        with (
            patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_cls,
            patch("alayaos_api.routers.integrator_runs.job_integrate", create=True) as mock_job,
        ):
            repo = AsyncMock()
            repo.create = AsyncMock(return_value=run)
            mock_cls.return_value = repo
            mock_job.kiq = AsyncMock()

            client = TestClient(app)
            response = client.post("/api/v1/integrator-runs/trigger", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 202
        data = response.json()["data"]
        assert data["trigger"] == "manual"

    def test_trigger_requires_admin_scope(self) -> None:
        """Trigger endpoint requires admin scope."""
        api_key = make_api_key(scopes=["read"])
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post("/api/v1/integrator-runs/trigger", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 403
