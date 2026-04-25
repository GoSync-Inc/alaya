"""Tests for GET /integrator-runs/{id}/trace endpoint."""

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
    auth_session = AsyncMock()
    route_session = AsyncMock()
    route_session.__aenter__ = AsyncMock(return_value=route_session)
    route_session.__aexit__ = AsyncMock(return_value=False)
    route_transaction = AsyncMock()
    route_transaction.__aenter__ = AsyncMock(return_value=None)

    async def close_transaction(*_args) -> bool:
        return False

    route_transaction.__aexit__ = AsyncMock(side_effect=close_transaction)
    route_session.begin = lambda: route_transaction
    app.state.route_session = route_session
    app.state.session_factory = lambda: route_session

    async def override_session():
        yield auth_session

    async def override_api_key():
        return api_key

    from alayaos_api.deps import get_api_key, get_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    return app


def make_integrator_run(ws_id: uuid.UUID | None = None):
    from alayaos_core.models.integrator_run import IntegratorRun

    now = datetime.now(UTC)
    run = IntegratorRun(
        id=uuid.uuid4(),
        workspace_id=ws_id or WS_ID,
        trigger="manual",
        scope_description="test",
        status="completed",
    )
    run.started_at = now
    return run


def make_trace(run_id: uuid.UUID, stage: str = "integrator:panoramic"):
    from alayaos_core.models.pipeline_trace import PipelineTrace

    trace = PipelineTrace(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        event_id=None,  # integrator traces have no event_id
        integrator_run_id=run_id,
        extraction_run_id=None,
        stage=stage,
        decision="",
        reason=None,
        details={"applied_actions": 3},
        tokens_used=20,
        tokens_in=15,
        tokens_out=5,
        tokens_cached=2,
        cache_write_5m_tokens=0,
        cache_write_1h_tokens=0,
        cost_usd=0.002,
        duration_ms=180,
    )
    trace.created_at = datetime.now(UTC)
    return trace


class TestIntegratorRunTraceRouter:
    def test_get_trace_returns_200_with_traces_list(self) -> None:
        """GET /integrator-runs/{id}/trace returns 200 with data list."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()
        trace = make_trace(run.id)

        with (
            patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_run_cls,
            patch("alayaos_api.routers.integrator_runs.PipelineTraceRepository") as mock_trace_cls,
        ):
            run_repo = AsyncMock()
            run_repo.get_by_id = AsyncMock(return_value=run)
            mock_run_cls.return_value = run_repo

            trace_repo = AsyncMock()
            trace_repo.list_by_integrator_run = AsyncMock(return_value=[trace])
            mock_trace_cls.return_value = trace_repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-runs/{run.id}/trace",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        items = body["data"]
        assert len(items) == 1
        item = items[0]
        assert item["stage"] == "integrator:panoramic"
        assert item["event_id"] is None  # integrator traces have no event_id
        assert item["integrator_run_id"] == str(run.id)
        assert item["tokens_in"] == 15
        assert item["tokens_out"] == 5
        assert item["tokens_cached"] == 2

    def test_get_trace_returns_empty_list_when_no_traces(self) -> None:
        """GET /integrator-runs/{id}/trace returns empty data list when no traces."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()

        with (
            patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_run_cls,
            patch("alayaos_api.routers.integrator_runs.PipelineTraceRepository") as mock_trace_cls,
        ):
            run_repo = AsyncMock()
            run_repo.get_by_id = AsyncMock(return_value=run)
            mock_run_cls.return_value = run_repo

            trace_repo = AsyncMock()
            trace_repo.list_by_integrator_run = AsyncMock(return_value=[])
            mock_trace_cls.return_value = trace_repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-runs/{run.id}/trace",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []

    def test_get_trace_returns_404_when_run_not_found(self) -> None:
        """GET /integrator-runs/{id}/trace returns 404 when run does not exist."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run_id = uuid.uuid4()

        with patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_run_cls:
            run_repo = AsyncMock()
            run_repo.get_by_id = AsyncMock(return_value=None)
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-runs/{run_id}/trace",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "resource.not_found"

    def test_get_trace_for_different_workspace_run_not_found(self) -> None:
        """GET /integrator-runs/{id}/trace returns 404 when run belongs to different workspace."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run_id = uuid.uuid4()

        with patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_run_cls:
            run_repo = AsyncMock()
            # Repo filters by workspace — run from another workspace returns None
            run_repo.get_by_id = AsyncMock(return_value=None)
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-runs/{run_id}/trace",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_get_trace_returns_multiple_phases(self) -> None:
        """GET /integrator-runs/{id}/trace returns all phases in order."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()
        traces = [
            make_trace(run.id, stage="integrator:panoramic"),
            make_trace(run.id, stage="integrator:dedup"),
            make_trace(run.id, stage="integrator:enricher"),
        ]

        with (
            patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_run_cls,
            patch("alayaos_api.routers.integrator_runs.PipelineTraceRepository") as mock_trace_cls,
        ):
            run_repo = AsyncMock()
            run_repo.get_by_id = AsyncMock(return_value=run)
            mock_run_cls.return_value = run_repo

            trace_repo = AsyncMock()
            trace_repo.list_by_integrator_run = AsyncMock(return_value=traces)
            mock_trace_cls.return_value = trace_repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-runs/{run.id}/trace",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 3
        stages = [item["stage"] for item in items]
        assert "integrator:panoramic" in stages
        assert "integrator:dedup" in stages
        assert "integrator:enricher" in stages
