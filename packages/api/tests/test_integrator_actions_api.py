"""Tests for integrator-actions API endpoint shape: v1 and v2 stamped actions.

Verifies backward compatibility: targets stays list-of-dicts, inverse v2 fields are present.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey
from alayaos_core.models.integrator_action import IntegratorAction

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
WS_ID = uuid.UUID("22345678-1234-5678-1234-567812345678")


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
    route_transaction.__aexit__ = AsyncMock(return_value=False)
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


def make_integrator_action(
    ws_id: uuid.UUID | None = None,
    action_type: str = "merge",
    snapshot_schema_version: int = 1,
    params: dict | None = None,
    targets: list | None = None,
    inverse: dict | None = None,
    run_id: uuid.UUID | None = None,
) -> IntegratorAction:
    now = datetime.now(UTC)
    action = IntegratorAction(
        id=uuid.uuid4(),
        workspace_id=ws_id or WS_ID,
        run_id=run_id or uuid.uuid4(),
        pass_number=1,
        action_type=action_type,
        status="applied",
        entity_id=uuid.uuid4(),
        params=params or {},
        targets=targets or [],
        inverse=inverse or {},
        snapshot_schema_version=snapshot_schema_version,
    )
    action.created_at = now
    action.applied_at = now
    action.reverted_at = None
    action.reverted_by = None
    action.trace_id = None
    action.model_id = None
    action.confidence = None
    action.rationale = None
    return action


class TestIntegratorActionsAPIShape:
    def test_api_read_legacy_merge_action_shape(self) -> None:
        """v1-stamped merge action: targets is list-of-dicts, API returns it unchanged."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # v1 action uses list-of-dicts targets (engine format)
        action = make_integrator_action(
            ws_id=WS_ID,
            action_type="merge",
            snapshot_schema_version=1,
            params={"loser_id": str(loser_id), "merged_name": "Alice"},
            targets=[
                {"id": str(winner_id), "name": "Alice"},
                {"id": str(loser_id), "name": "Alicia"},
            ],
            inverse={"action": "unmerge", "loser_id": str(loser_id)},
            run_id=run_id,
        )

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.list_by_run = AsyncMock(return_value=([action], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-actions?run_id={run_id}",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1

        item = body["data"][0]
        # snapshot_schema_version must be exposed
        assert item["snapshot_schema_version"] == 1

        # targets must be list-of-dicts (shape preserved)
        targets = item["targets"]
        assert isinstance(targets, list)
        assert len(targets) == 2
        for t in targets:
            assert isinstance(t, dict)
            assert "id" in t
            assert "name" in t

        # params must be preserved
        assert item["params"]["loser_id"] == str(loser_id)

    def test_api_read_v2_merge_action_shape(self) -> None:
        """v2-stamped action: targets unchanged AND inverse contains v2 fields."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()
        run_id = uuid.uuid4()
        claim_id = uuid.uuid4()

        # v2 action with full inverse payload
        v2_inverse = {
            "action": "unmerge",
            "loser_id": str(loser_id),
            "moved_claim_ids": [str(claim_id)],
            "moved_relation_source_ids": [],
            "moved_relation_target_ids": [],
            "moved_chunk_ids": [],
            "deleted_self_ref_relation_ids": [],
            "deduplicated_relation_ids": [],
            "winner_before": {"name": "Alice", "description": "", "aliases": []},
        }

        action = make_integrator_action(
            ws_id=WS_ID,
            action_type="merge",
            snapshot_schema_version=2,
            params={"loser_id": str(loser_id), "merged_name": "Alice"},
            targets=[
                {"id": str(winner_id), "name": "Alice"},
                {"id": str(loser_id), "name": "Alicia"},
            ],
            inverse=v2_inverse,
            run_id=run_id,
        )

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.list_by_run = AsyncMock(return_value=([action], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-actions?run_id={run_id}",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1

        item = body["data"][0]
        assert item["snapshot_schema_version"] == 2

        # targets must be unchanged (list-of-dicts)
        targets = item["targets"]
        assert isinstance(targets, list)
        assert len(targets) == 2
        for t in targets:
            assert isinstance(t, dict)
            assert "id" in t
            assert "name" in t

        # inverse must contain all v2 fields
        inverse = item["inverse"]
        v2_fields = [
            "moved_claim_ids",
            "moved_relation_source_ids",
            "moved_relation_target_ids",
            "moved_chunk_ids",
            "deleted_self_ref_relation_ids",
            "deduplicated_relation_ids",
            "winner_before",
        ]
        for field in v2_fields:
            assert field in inverse, f"Missing v2 inverse field in API response: {field!r}"

        # moved_claim_ids must contain our claim_id
        assert str(claim_id) in inverse["moved_claim_ids"]

    def test_api_read_dedup_merge_action_shape(self) -> None:
        """Dedup v2 merge action: targets is list-of-strings (dedup producer format), preserved."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        loser_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # Dedup uses targets=[str(loser_id)] (list-of-strings)
        action = make_integrator_action(
            ws_id=WS_ID,
            action_type="merge",
            snapshot_schema_version=2,
            params={
                "name": "Alice Johnson",
                "description": "Senior engineer",
                "aliases": ["AJ"],
            },
            targets=[str(loser_id)],  # dedup format: list of strings
            inverse={
                "action": "unmerge",
                "loser_id": str(loser_id),
                "moved_claim_ids": [],
                "moved_relation_source_ids": [],
                "moved_relation_target_ids": [],
                "moved_chunk_ids": [],
                "deleted_self_ref_relation_ids": [],
                "deduplicated_relation_ids": [],
                "winner_before": {"name": "Alice", "description": "", "aliases": []},
            },
            run_id=run_id,
        )

        with patch("alayaos_api.routers.integrator_runs.IntegratorActionRepository") as mock_cls:
            repo = AsyncMock()
            repo.list_by_run = AsyncMock(return_value=([action], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(
                f"/api/v1/integrator-actions?run_id={run_id}",
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 200
        body = response.json()
        item = body["data"][0]

        # targets must be list-of-strings (dedup format preserved)
        targets = item["targets"]
        assert isinstance(targets, list)
        assert len(targets) == 1
        assert targets[0] == str(loser_id)

        # params must be preserved (dedup format: name/description/aliases)
        assert "name" in item["params"]
        assert "description" in item["params"]
        assert "aliases" in item["params"]
