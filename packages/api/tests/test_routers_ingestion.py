"""Tests for the ingestion router."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


def _mock_redis_client() -> MagicMock:
    client = MagicMock()
    client.aclose = AsyncMock()
    return client


def _patch_rate_limiter(allowed: bool = True, retry_after: int | None = None, backend_available: bool = True):
    """Return a patcher for RateLimiterService that yields the given decision."""
    redis_client = _mock_redis_client()

    def _apply(stack):
        stack.enter_context(patch("alayaos_api.routers.ingestion.aioredis.from_url", return_value=redis_client))
        mock_limiter_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.RateLimiterService"))
        mock_limiter_cls.return_value.check = AsyncMock(
            return_value=SimpleNamespace(allowed=allowed, retry_after=retry_after, backend_available=backend_available)
        )

    return _apply


class TestIngestionRouter:
    def test_ingest_text_returns_202(self) -> None:
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        run = make_run(event.id)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))

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
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        run = make_run(event.id)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))

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
        event_repo.create_or_update.assert_called_once()
        call_kwargs = event_repo.create_or_update.call_args
        source_id = call_kwargs.kwargs.get("source_id") or call_kwargs.args[2]
        assert source_id is not None
        uuid.UUID(str(source_id))

    def test_ingest_text_returns_429_when_rate_limited(self) -> None:
        """Rate limit exceeded → 429 with Retry-After header (applied upstream)."""
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with ExitStack() as stack:
            _patch_rate_limiter(allowed=False, retry_after=12, backend_available=True)(stack)

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "test"},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "12"
        assert response.json()["error"]["code"] == "rate_limit.exceeded"

    def test_ingest_text_returns_503_when_rate_limiter_backend_unavailable(self) -> None:
        """Redis outage → fail-closed with 503, not unthrottled passthrough."""
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with ExitStack() as stack:
            _patch_rate_limiter(allowed=False, retry_after=None, backend_available=False)(stack)

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "test"},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "server.rate_limit_unavailable"

    def test_ingest_text_idempotent_retry_returns_same_pending_run(self) -> None:
        """Retry with existing source_id → same pending run, kiq re-enqueued
        (recovery path for broker outages — codex review).
        """
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        pending_run = make_run(event.id)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))
            mock_job_extract = stack.enter_context(patch("alayaos_core.worker.tasks.job_extract"))
            mock_job_extract.kiq = AsyncMock()

            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, False))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.list_by_event = AsyncMock(return_value=[pending_run])
            run_repo.create = AsyncMock()
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "retry", "source_id": str(event.source_id)},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        # No new run created — same pending returned.
        run_repo.create.assert_not_called()
        # kiq IS re-enqueued so a dropped enqueue (broker outage) recovers.
        mock_job_extract.kiq.assert_called_once()
        assert str(pending_run.id) == response.json()["data"]["extraction_run_id"]

    def test_ingest_text_after_skipped_run_starts_fresh_extraction(self) -> None:
        """A previously ``skipped`` run (access denied) must not block retries.

        Regression for codex 6th review: the ``active`` filter previously
        treated ``skipped`` as a blocking status, preventing reprocessing
        after access_level changes.
        """
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        skipped_run = make_run(event.id)
        skipped_run.status = "skipped"
        new_run = make_run(event.id)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))
            mock_job_extract = stack.enter_context(patch("alayaos_core.worker.tasks.job_extract"))
            mock_job_extract.kiq = AsyncMock()

            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, False))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.list_by_event = AsyncMock(return_value=[skipped_run])
            run_repo.create = AsyncMock(return_value=new_run)
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "retry-after-access-change", "source_id": str(event.source_id)},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        # New run created with parent_run_id pointing at the skipped one.
        run_repo.create.assert_called_once()
        create_kwargs = run_repo.create.call_args.kwargs
        assert create_kwargs["parent_run_id"] == skipped_run.id
        # Fresh kiq for the new run.
        mock_job_extract.kiq.assert_called_once()

    def test_ingest_text_prefers_pending_over_newer_extracting(self) -> None:
        """When both pending and extracting runs exist (concurrent-ingest race),
        a retry must pick the pending one so recovery works (codex 8th review).
        """
        from contextlib import ExitStack

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        old_pending = make_run(event.id)
        old_pending.status = "pending"
        new_extracting = make_run(event.id)
        new_extracting.status = "extracting"
        # Newer timestamp on the in-progress run: simulates race where the
        # second concurrent request's run started processing first.
        new_extracting.created_at = old_pending.created_at.replace(microsecond=999999)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))
            mock_job_extract = stack.enter_context(patch("alayaos_core.worker.tasks.job_extract"))
            mock_job_extract.kiq = AsyncMock()

            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, False))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.list_by_event = AsyncMock(return_value=[old_pending, new_extracting])
            run_repo.create = AsyncMock()
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "retry", "source_id": str(event.source_id)},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        # Must return the pending run (recovery target), NOT the newer extracting one.
        assert str(old_pending.id) == response.json()["data"]["extraction_run_id"]
        # Recovery-re-enqueue must happen.
        mock_job_extract.kiq.assert_called_once()

    def test_ingest_text_does_not_reenqueue_fresh_extracting_run(self) -> None:
        """Retry while worker is processing (fresh 'extracting') must NOT re-kiq.

        Regression for codex review P1: job_extract only skips terminal
        statuses, so re-enqueuing against an ``extracting`` run within the
        stale threshold would double-process the event.
        """
        from contextlib import ExitStack
        from datetime import UTC, datetime

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        extracting_run = make_run(event.id)
        extracting_run.status = "extracting"
        # Fresh run — well inside the 10-min stale threshold.
        extracting_run.created_at = datetime.now(UTC)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))
            mock_job_extract = stack.enter_context(patch("alayaos_core.worker.tasks.job_extract"))
            mock_job_extract.kiq = AsyncMock()

            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, False))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.list_by_event = AsyncMock(return_value=[extracting_run])
            run_repo.create = AsyncMock()
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "retry", "source_id": str(event.source_id)},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        run_repo.create.assert_not_called()
        mock_job_extract.kiq.assert_not_called()
        assert str(extracting_run.id) == response.json()["data"]["extraction_run_id"]

    def test_ingest_text_reenqueues_stale_extracting_run(self) -> None:
        """Stuck 'extracting' run past the stale threshold must re-kiq.

        Regression for codex 9th review P1: without best-effort recovery,
        a dead worker would leave events permanently stuck.
        """
        from contextlib import ExitStack
        from datetime import UTC, datetime, timedelta

        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        event = make_event()
        stuck_run = make_run(event.id)
        stuck_run.status = "extracting"
        # 30 minutes old — clearly past the 10-min stale threshold.
        stuck_run.created_at = datetime.now(UTC) - timedelta(minutes=30)

        with ExitStack() as stack:
            _patch_rate_limiter()(stack)
            mock_event_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.EventRepository"))
            mock_run_cls = stack.enter_context(patch("alayaos_api.routers.ingestion.ExtractionRunRepository"))
            mock_job_extract = stack.enter_context(patch("alayaos_core.worker.tasks.job_extract"))
            mock_job_extract.kiq = AsyncMock()

            event_repo = AsyncMock()
            event_repo.create_or_update = AsyncMock(return_value=(event, False))
            mock_event_cls.return_value = event_repo

            run_repo = AsyncMock()
            run_repo.list_by_event = AsyncMock(return_value=[stuck_run])
            run_repo.create = AsyncMock()
            mock_run_cls.return_value = run_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/ingest/text",
                json={"text": "retry", "source_id": str(event.source_id)},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 202
        run_repo.create.assert_not_called()  # reuse the stuck run, don't create new
        # Recovery: kiq IS called to revive processing.
        mock_job_extract.kiq.assert_called_once()
        assert str(stuck_run.id) == response.json()["data"]["extraction_run_id"]
