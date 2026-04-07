"""Tests for the ingestion router."""

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


def make_event():
    from alayaos_core.models.event import L0Event

    now = datetime.now(UTC)
    event = L0Event(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        source_type="manual",
        source_id=str(uuid.uuid4()),
        content={"text": "hello"},
        event_metadata={},
    )
    event.created_at = now
    event.updated_at = now
    return event


def make_run(event_id: uuid.UUID):
    from alayaos_core.models.extraction_run import ExtractionRun

    now = datetime.now(UTC)
    run = ExtractionRun(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        event_id=event_id,
        status="pending",
        tokens_in=0,
        tokens_out=0,
        cost_usd=0,
        entities_created=0,
        entities_merged=0,
        relations_created=0,
        claims_created=0,
        claims_superseded=0,
        resolver_decisions=[],
        error_detail={},
        retry_count=0,
    )
    run.created_at = now
    run.updated_at = now
    return run


class TestIngestionRouter:
    def test_ingest_text_returns_202(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        run = make_run(event.id)

        with (
            patch("alayaos_api.routers.ingestion.EventRepository") as mock_event_cls,
            patch("alayaos_api.routers.ingestion.ExtractionRunRepository") as mock_run_cls,
        ):
            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, True))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.create = AsyncMock(return_value=run)
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "This is a test document about Alice and Bob."},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        body = response.json()
        assert "data" in body
        assert "event_id" in body["data"]
        assert "extraction_run_id" in body["data"]
        assert body["data"]["status"] == "pending"

    def test_ingest_text_too_long_returns_422(self) -> None:
        """Text exceeding 100K chars is rejected with validation.text_too_long."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post(
            "/api/v1/ingest/text",
            json={"text": "x" * 100001},
            headers={"X-Api-Key": RAW_KEY},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation.text_too_long"

    def test_ingest_text_auto_source_id(self) -> None:
        """When source_id is not provided, a UUID is auto-generated."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        run = make_run(event.id)

        with (
            patch("alayaos_api.routers.ingestion.EventRepository") as mock_event_cls,
            patch("alayaos_api.routers.ingestion.ExtractionRunRepository") as mock_run_cls,
        ):
            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, True))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.create = AsyncMock(return_value=run)
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "Some content without source_id"},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        # Verify auto-generated source_id was used (event_repo.create_or_update was called)
        event_repo.create_or_update.assert_called_once()
        call_kwargs = event_repo.create_or_update.call_args
        # source_id should be a valid UUID string
        source_id = call_kwargs.kwargs.get("source_id") or call_kwargs.args[2]
        assert source_id is not None
        # Should be parseable as UUID
        uuid.UUID(str(source_id))
