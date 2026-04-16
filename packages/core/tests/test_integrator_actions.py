"""Tests for IntegratorAction model, schemas, and repository."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── Helpers ─────────────────────────────────────────────────────────────────


def make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = MagicMock()
    return session


def make_result(obj) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj else []
    return result


def make_scalar_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _make_action(
    ws_id: uuid.UUID | None = None,
    action_type: str = "remove_noise",
    run_id: uuid.UUID | None = None,
):
    from alayaos_core.models.integrator_action import IntegratorAction

    now = datetime.now(UTC)
    action = IntegratorAction(
        id=uuid.uuid4(),
        workspace_id=ws_id or uuid.uuid4(),
        run_id=run_id or uuid.uuid4(),
        pass_number=1,
        action_type=action_type,
        status="applied",
        params={},
        targets=[],
        inverse={},
        snapshot_schema_version=1,
    )
    action.created_at = now
    return action


# ─── Schema tests ─────────────────────────────────────────────────────────────


class TestIntegratorActionSchemas:
    def test_create_schema_validates_required_fields(self) -> None:
        from alayaos_core.schemas.integrator_action import IntegratorActionCreate

        data = IntegratorActionCreate(
            run_id=uuid.uuid4(),
            pass_number=1,
            action_type="remove_noise",
            entity_id=uuid.uuid4(),
            params={},
            targets=[],
            inverse={},
        )
        assert data.action_type == "remove_noise"
        assert data.pass_number == 1

    def test_read_schema_from_attributes(self) -> None:
        from alayaos_core.schemas.integrator_action import IntegratorActionRead

        action = _make_action()
        read = IntegratorActionRead.model_validate(action)
        assert read.action_type == "remove_noise"
        assert read.status == "applied"
        assert read.pass_number == 1

    def test_rollback_response_schema(self) -> None:
        from alayaos_core.schemas.integrator_action import IntegratorActionRollbackResponse

        resp = IntegratorActionRollbackResponse(
            reverted_action_id=uuid.uuid4(),
            conflicts=[],
        )
        assert resp.conflicts == []

    def test_rollback_response_with_conflicts(self) -> None:
        from alayaos_core.schemas.integrator_action import IntegratorActionRollbackResponse

        aid = uuid.uuid4()
        resp = IntegratorActionRollbackResponse(
            reverted_action_id=aid,
            conflicts=["entity_type changed since action"],
        )
        assert len(resp.conflicts) == 1
        assert resp.reverted_action_id == aid


# ─── Repository: create + read ────────────────────────────────────────────────


class TestIntegratorActionRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_action_and_read_back(self) -> None:
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository
        from alayaos_core.schemas.integrator_action import IntegratorActionCreate

        ws_id = uuid.uuid4()
        run_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        expected = _make_action(ws_id=ws_id, action_type="reclassify", run_id=run_id)
        expected.entity_id = entity_id

        session = make_session()
        session.execute.return_value = make_result(expected)

        repo = IntegratorActionRepository(session, ws_id)
        data = IntegratorActionCreate(
            run_id=run_id,
            pass_number=1,
            action_type="reclassify",
            entity_id=entity_id,
            params={"new_type_id": str(uuid.uuid4())},
            targets=[],
            inverse={"old_type_id": str(uuid.uuid4())},
        )
        action = await repo.create(ws_id, data)
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert action.action_type == "reclassify"
        assert action.entity_id == entity_id

    @pytest.mark.asyncio
    async def test_get_by_id(self) -> None:
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        action = _make_action(ws_id=ws_id)

        session = make_session()
        session.execute.return_value = make_result(action)

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.get_by_id(ws_id, action.id)
        assert result is action

    @pytest.mark.asyncio
    async def test_get_by_id_missing_returns_none(self) -> None:
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        session = make_session()
        session.execute.return_value = make_result(None)

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.get_by_id(ws_id, uuid.uuid4())
        assert result is None


# ─── Repository: list_by_run ──────────────────────────────────────────────────


class TestIntegratorActionRepositoryList:
    @pytest.mark.asyncio
    async def test_list_by_run(self) -> None:
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        run_id = uuid.uuid4()
        now = datetime.now(UTC)
        actions = [_make_action(ws_id=ws_id, run_id=run_id) for _ in range(3)]
        for a in actions:
            a.created_at = now

        session = make_session()
        session.execute.return_value = make_scalar_result(actions)

        repo = IntegratorActionRepository(session, ws_id)
        items, cursor, has_more = await repo.list_by_run(ws_id, run_id, cursor=None, limit=10)
        assert len(items) == 3
        assert has_more is False
        assert cursor is None

    @pytest.mark.asyncio
    async def test_list_by_run_has_more(self) -> None:
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        run_id = uuid.uuid4()
        now = datetime.now(UTC)
        # simulate limit+1 items returned
        actions = [_make_action(ws_id=ws_id, run_id=run_id) for _ in range(4)]
        for a in actions:
            a.created_at = now

        session = make_session()
        session.execute.return_value = make_scalar_result(actions)

        repo = IntegratorActionRepository(session, ws_id)
        items, cursor, has_more = await repo.list_by_run(ws_id, run_id, cursor=None, limit=3)
        assert len(items) == 3
        assert has_more is True
        assert cursor is not None


# ─── Repository: rollback logic ───────────────────────────────────────────────


class TestIntegratorActionRollback:
    @pytest.mark.asyncio
    async def test_rollback_remove_noise_undeletes_entity(self) -> None:
        """Rollback of remove_noise sets entity.is_deleted = False."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="remove_noise")
        action.entity_id = entity_id
        action.status = "applied"

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Noise entity",
            properties={},
            is_deleted=True,
        )
        entity.external_ids = []

        session = make_session()
        # First execute returns the action, subsequent execute returns the entity
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        assert entity.is_deleted is False
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_reclassify_reverts_entity_type(self) -> None:
        """Rollback of reclassify reverts entity_type_id from inverse snapshot."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        old_type_id = uuid.uuid4()
        new_type_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="reclassify")
        action.entity_id = entity_id
        action.status = "applied"
        action.params = {"new_type_id": str(new_type_id)}
        action.inverse = {"old_type_id": str(old_type_id)}

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=new_type_id,  # currently has new type
            name="Some entity",
            properties={},
            is_deleted=False,
        )
        entity.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        assert entity.entity_type_id == old_type_id
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_reclassify_conflict_when_type_changed(self) -> None:
        """Rollback refused if entity_type changed since action."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        old_type_id = uuid.uuid4()
        new_type_id = uuid.uuid4()
        other_type_id = uuid.uuid4()  # someone else changed it

        action = _make_action(ws_id=ws_id, action_type="reclassify")
        action.entity_id = entity_id
        action.status = "applied"
        action.params = {"new_type_id": str(new_type_id)}
        action.inverse = {"old_type_id": str(old_type_id)}

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=other_type_id,  # different from what action set
            name="Some entity",
            properties={},
            is_deleted=False,
        )
        entity.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert len(result.conflicts) == 1
        assert "entity_type" in result.conflicts[0]
        # entity_type_id should NOT have been changed
        assert entity.entity_type_id == other_type_id

    @pytest.mark.asyncio
    async def test_rollback_reclassify_conflict_force_overrides(self) -> None:
        """Rollback with force=True applies even on conflict."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        old_type_id = uuid.uuid4()
        new_type_id = uuid.uuid4()
        other_type_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="reclassify")
        action.entity_id = entity_id
        action.status = "applied"
        action.params = {"new_type_id": str(new_type_id)}
        action.inverse = {"old_type_id": str(old_type_id)}

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=other_type_id,
            name="Some entity",
            properties={},
            is_deleted=False,
        )
        entity.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        await repo.apply_rollback(ws_id, action.id, force=True)
        assert entity.entity_type_id == old_type_id
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_rewrite_reverts_name_description(self) -> None:
        """Rollback of rewrite reverts name+description from inverse snapshot."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="rewrite")
        action.entity_id = entity_id
        action.status = "applied"
        action.params = {"name": "New Name", "description": "New Desc"}
        action.inverse = {"name": "Old Name", "description": "Old Desc"}

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="New Name",
            description="New Desc",
            properties={},
            is_deleted=False,
        )
        entity.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        assert entity.name == "Old Name"
        assert entity.description == "Old Desc"
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_rewrite_conflict_when_name_changed_downstream(self) -> None:
        """Rollback refused if entity name/desc differs from 'after' snapshot."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="rewrite")
        action.entity_id = entity_id
        action.status = "applied"
        action.params = {"name": "New Name", "description": "New Desc"}
        action.inverse = {"name": "Old Name", "description": "Old Desc"}

        entity = L1Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Someone Else Changed It",  # downstream edit
            description="New Desc",
            properties={},
            is_deleted=False,
        )
        entity.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(entity)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert len(result.conflicts) > 0
        assert "name" in result.conflicts[0]
        assert entity.name == "Someone Else Changed It"  # unchanged

    @pytest.mark.asyncio
    async def test_rollback_merge_restores_loser(self) -> None:
        """Rollback of merge: loser entity is restored (is_deleted=False)."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="merge")
        action.entity_id = winner_id
        action.status = "applied"
        action.params = {"winner_id": str(winner_id), "loser_id": str(loser_id)}
        action.inverse = {"loser_id": str(loser_id)}
        action.targets = [str(loser_id)]

        loser = L1Entity(
            id=loser_id,
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Loser",
            properties={},
            is_deleted=True,
        )
        loser.external_ids = []

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(loser)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        assert loser.is_deleted is False
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_create_from_cluster_deletes_synthetic_entity(self) -> None:
        """Rollback of create_from_cluster deletes the synthetic entity."""
        from alayaos_core.models.entity import L1Entity
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        synthetic_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="create_from_cluster")
        action.entity_id = synthetic_id
        action.status = "applied"
        action.params = {}
        action.inverse = {}

        synthetic = L1Entity(
            id=synthetic_id,
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Synthetic",
            properties={},
            is_deleted=False,
        )
        synthetic.external_ids = []

        session = make_session()
        # First call for get action, second for get entity
        session.execute.side_effect = [make_result(action), make_result(synthetic)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        assert synthetic.is_deleted is True
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_link_cross_type_soft_deletes_relation(self) -> None:
        """Rollback of link_cross_type soft-deletes the created relation via is_deleted on entity."""
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        relation_id = uuid.uuid4()

        action = _make_action(ws_id=ws_id, action_type="link_cross_type")
        action.entity_id = None
        action.status = "applied"
        action.params = {"relation_id": str(relation_id)}
        action.inverse = {}
        action.targets = [str(relation_id)]

        from alayaos_core.models.relation import L1Relation

        rel = L1Relation(
            id=relation_id,
            workspace_id=ws_id,
            source_entity_id=uuid.uuid4(),
            target_entity_id=uuid.uuid4(),
            relation_type="cross_type",
            confidence=1.0,
        )

        session = make_session()
        session.execute.side_effect = [make_result(action), make_result(rel)]

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result.conflicts == []
        session.delete.assert_called_once_with(rel)
        assert action.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_action_not_found_returns_none(self) -> None:
        """apply_rollback returns None when action not found."""
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        session = make_session()
        session.execute.return_value = make_result(None)

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_rollback_already_rolled_back_is_noop(self) -> None:
        """apply_rollback on already-rolled-back action returns response with no conflicts."""
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        action = _make_action(ws_id=ws_id, action_type="remove_noise")
        action.status = "rolled_back"

        session = make_session()
        session.execute.return_value = make_result(action)

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result is not None
        assert result.conflicts == []

    @pytest.mark.asyncio
    async def test_rollback_unknown_action_type_returns_conflict_not_rolled_back(self) -> None:
        """apply_rollback with unknown action_type returns conflict message and does NOT mark action as rolled_back."""
        from alayaos_core.repositories.integrator_action import IntegratorActionRepository

        ws_id = uuid.uuid4()
        action = _make_action(ws_id=ws_id, action_type="unknown_future_action")
        action.status = "applied"

        session = make_session()
        session.execute.return_value = make_result(action)

        repo = IntegratorActionRepository(session, ws_id)
        result = await repo.apply_rollback(ws_id, action.id)
        assert result is not None
        assert len(result.conflicts) == 1
        assert "unknown_future_action" in result.conflicts[0]
        # action must remain applied, not rolled_back
        assert action.status == "applied"
