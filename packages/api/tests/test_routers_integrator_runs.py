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
    auth_session = AsyncMock()
    route_session = AsyncMock()
    route_session.__aenter__ = AsyncMock(return_value=route_session)
    route_session.__aexit__ = AsyncMock(return_value=False)
    route_transaction = AsyncMock()
    route_transaction.__aenter__ = AsyncMock(return_value=None)

    async def close_transaction(*_args) -> bool:
        app.state.run_transaction_closed = True
        return False

    route_transaction.__aexit__ = AsyncMock(side_effect=close_transaction)
    route_session.begin = lambda: route_transaction
    app.state.run_transaction_closed = False
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
            patch("alayaos_core.worker.tasks.job_integrate") as mock_job,
        ):
            repo = AsyncMock()
            repo.create = AsyncMock(return_value=run)
            mock_cls.return_value = repo

            async def assert_committed(*_args) -> None:
                assert app.state.run_transaction_closed is True

            mock_job.kiq = AsyncMock(side_effect=assert_committed)

            client = TestClient(app)
            response = client.post("/api/v1/integrator-runs/trigger", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 202
        data = response.json()["data"]
        assert data["trigger"] == "manual"
        args, _ = app.state.route_session.execute.call_args
        sql_clause = args[0]
        assert hasattr(sql_clause, "text")
        assert "SET LOCAL app.workspace_id" in sql_clause.text
        assert str(WS_ID) in sql_clause.text
        mock_job.kiq.assert_awaited_once_with(str(WS_ID), str(run.id))

    def test_trigger_integrator_run_marks_failed_when_enqueue_fails(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()

        with (
            patch("alayaos_api.routers.integrator_runs.IntegratorRunRepository") as mock_cls,
            patch("alayaos_core.worker.tasks.job_integrate") as mock_job,
        ):
            repo = AsyncMock()
            repo.create = AsyncMock(return_value=run)
            repo.update_status = AsyncMock(return_value=run)
            mock_cls.return_value = repo
            mock_job.kiq = AsyncMock(side_effect=RuntimeError("broker unavailable"))

            client = TestClient(app)
            response = client.post("/api/v1/integrator-runs/trigger", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service.integrator_enqueue_failed"
        repo.update_status.assert_awaited_once_with(
            run.id,
            "failed",
            error_message="broker unavailable",
        )

    def test_trigger_requires_admin_scope(self) -> None:
        """Trigger endpoint requires admin scope."""
        api_key = make_api_key(scopes=["read"])
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post("/api/v1/integrator-runs/trigger", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 403


class TestIntegratorActionRollbackRouter:
    def test_rollback_action_success_returns_200(self) -> None:
        """Rollback with no conflicts returns 200."""
        from alayaos_core.schemas.integrator_action import IntegratorActionRollbackResponse

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        action_id = uuid.uuid4()
        response_obj = IntegratorActionRollbackResponse(
            reverted_action_id=action_id,
            conflicts=[],
        )

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.apply_rollback = AsyncMock(return_value=response_obj)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.post(
                f"/api/v1/integrator-actions/{action_id}/rollback",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200

    def test_rollback_action_not_found_returns_404(self) -> None:
        """Rollback on missing action returns 404."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        action_id = uuid.uuid4()

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.apply_rollback = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.post(
                f"/api/v1/integrator-actions/{action_id}/rollback",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_rollback_action_with_conflicts_returns_409(self) -> None:
        """Rollback with conflicts (action not rolled back) returns HTTP 409."""
        from alayaos_core.schemas.integrator_action import IntegratorActionRollbackResponse

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        action_id = uuid.uuid4()
        response_obj = IntegratorActionRollbackResponse(
            reverted_action_id=action_id,
            conflicts=["name changed since action: expected 'Old', found 'New'"],
        )

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.apply_rollback = AsyncMock(return_value=response_obj)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.post(
                f"/api/v1/integrator-actions/{action_id}/rollback",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 409
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "action.rollback_conflict"


class TestIntegratorRunTraceEndpoint:
    """Tests for GET /integrator-runs/{id}/trace."""

    def _make_trace(self, run_id: uuid.UUID):
        from alayaos_core.models.pipeline_trace import PipelineTrace

        trace = PipelineTrace(
            id=uuid.uuid4(),
            workspace_id=WS_ID,
            event_id=None,
            integrator_run_id=run_id,
            extraction_run_id=None,
            stage="integrator:panoramic",
            decision="",
            reason=None,
            details={},
            tokens_used=15,
            tokens_in=10,
            tokens_out=5,
            tokens_cached=0,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            cost_usd=0.001,
            duration_ms=120,
        )
        trace.created_at = datetime.now(UTC)
        return trace

    def test_get_integrator_run_trace_returns_200(self) -> None:
        """GET /integrator-runs/{id}/trace returns traces list with granular token fields."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        run = make_integrator_run()
        trace = self._make_trace(run.id)

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
        assert item["tokens_in"] == 10
        assert item["tokens_out"] == 5
        assert item["integrator_run_id"] == str(run.id)

    def test_get_integrator_run_trace_returns_404_when_run_not_found(self) -> None:
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
        assert response.json()["error"]["code"] == "resource.not_found"
