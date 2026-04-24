"""Integration test: panoramic hierarchy guard.

Verifies that _apply_single_panoramic_action (via create_from_cluster and
link_cross_type) rejects part_of relations that violate ENTITY_TYPE_TIER_RANK,
logs panoramic_part_of_rejected, and does not propagate the error.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing

from alayaos_core.extraction.integrator.engine import IntegratorEngine
from alayaos_core.extraction.integrator.passes.panoramic import PanoramicAction
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.entity_type import EntityTypeRepository
from alayaos_core.repositories.relation import RelationRepository

pytestmark = pytest.mark.integration


def _make_settings():
    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_MODEL = "claude-test"
    settings.INTEGRATOR_DEDUP_SHORTLIST_K = 5
    settings.INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_BATCH_SIZE = 9
    return settings


@pytest.mark.asyncio
async def test_create_from_cluster_rejects_inverted_tier(workspace, db_session):
    """create_from_cluster: child=project, parent=task → rejected with log, no DB row."""
    ws_id = workspace.id

    # Seed a project entity that will be the "child" attempting to be part_of a new task
    project_type_id = (await EntityTypeRepository(db_session, ws_id).get_by_slug(ws_id, "project")).id
    # task_type_id not needed here — new parent entity is created by the panoramic action itself

    entity_repo = EntityRepository(db_session, ws_id)
    project = await entity_repo.create(workspace_id=ws_id, entity_type_id=project_type_id, name="ChildProject")
    await db_session.flush()

    relation_repo = RelationRepository(db_session, ws_id)

    engine = IntegratorEngine(
        llm=AsyncMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=relation_repo,
        entity_cache=AsyncMock(),
        redis=AsyncMock(),
        settings=_make_settings(),
    )

    # create_from_cluster: create a new entity of type "task" as parent,
    # with the project as a child → part_of(project, new_task) is inverted
    action = PanoramicAction(
        action="create_from_cluster",
        entity_id=None,
        params={
            "name": "ParentTask",
            "entity_type": "task",  # parent is a task
            "child_ids": [str(project.id)],  # child is a project → inverted!
        },
        confidence=0.9,
        rationale="test",
    )

    run_id = uuid.uuid4()

    with structlog.testing.capture_logs() as cap_logs:
        await engine._apply_panoramic_actions(
            [action],
            ws_id,
            run_id,
            pass_number=1,
            session=db_session,
            action_repo=None,
        )

    # The action itself "applied" (create_from_cluster doesn't fail even if relations fail)
    # but the part_of relation was not created
    rejection_events = [e for e in cap_logs if e.get("event") == "panoramic_part_of_rejected"]
    assert len(rejection_events) >= 1, (
        f"Expected panoramic_part_of_rejected log, got events: {[e.get('event') for e in cap_logs]}"
    )


@pytest.mark.asyncio
async def test_link_cross_type_rejects_inverted_part_of(workspace, db_session):
    """link_cross_type: part_of(goal, project) where goal>project → rejected with log."""
    ws_id = workspace.id

    goal_type_id = (await EntityTypeRepository(db_session, ws_id).get_by_slug(ws_id, "goal")).id
    project_type_id = (await EntityTypeRepository(db_session, ws_id).get_by_slug(ws_id, "project")).id

    entity_repo = EntityRepository(db_session, ws_id)
    goal = await entity_repo.create(workspace_id=ws_id, entity_type_id=goal_type_id, name="BigGoal")
    project = await entity_repo.create(workspace_id=ws_id, entity_type_id=project_type_id, name="SmallProject")
    await db_session.flush()

    relation_repo = RelationRepository(db_session, ws_id)

    engine = IntegratorEngine(
        llm=AsyncMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=relation_repo,
        entity_cache=AsyncMock(),
        redis=AsyncMock(),
        settings=_make_settings(),
    )

    # link_cross_type: part_of(project, goal) is valid (project=2 < goal=3)
    # But here we do the inverted: source=goal(rank=3), target=project(rank=2) → invalid
    action = PanoramicAction(
        action="link_cross_type",
        entity_id=goal.id,
        params={
            "source_id": str(goal.id),
            "target_id": str(project.id),
            "relation_type": "part_of",
        },
        confidence=0.8,
        rationale="test inverted",
    )

    run_id = uuid.uuid4()

    with structlog.testing.capture_logs() as cap_logs:
        await engine._apply_panoramic_actions(
            [action],
            ws_id,
            run_id,
            pass_number=1,
            session=db_session,
            action_repo=None,
        )

    rejection_events = [e for e in cap_logs if e.get("event") == "panoramic_part_of_rejected"]
    assert len(rejection_events) >= 1, (
        f"Expected panoramic_part_of_rejected log, got events: {[e.get('event') for e in cap_logs]}"
    )


@pytest.mark.asyncio
async def test_link_cross_type_valid_part_of_lands(workspace, db_session):
    """link_cross_type: part_of(task, project) is valid and lands in DB."""
    ws_id = workspace.id

    task_type_id = (await EntityTypeRepository(db_session, ws_id).get_by_slug(ws_id, "task")).id
    project_type_id = (await EntityTypeRepository(db_session, ws_id).get_by_slug(ws_id, "project")).id

    entity_repo = EntityRepository(db_session, ws_id)
    task = await entity_repo.create(workspace_id=ws_id, entity_type_id=task_type_id, name="T1")
    project = await entity_repo.create(workspace_id=ws_id, entity_type_id=project_type_id, name="P1")
    await db_session.flush()

    relation_repo = RelationRepository(db_session, ws_id)

    engine = IntegratorEngine(
        llm=AsyncMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=relation_repo,
        entity_cache=AsyncMock(),
        redis=AsyncMock(),
        settings=_make_settings(),
    )

    # Valid: task(rank=1) part_of project(rank=2)
    action = PanoramicAction(
        action="link_cross_type",
        entity_id=task.id,
        params={
            "source_id": str(task.id),
            "target_id": str(project.id),
            "relation_type": "part_of",
        },
        confidence=0.9,
        rationale="valid",
    )

    run_id = uuid.uuid4()

    with structlog.testing.capture_logs() as cap_logs:
        applied = await engine._apply_panoramic_actions(
            [action],
            ws_id,
            run_id,
            pass_number=1,
            session=db_session,
            action_repo=None,
        )

    rejection_events = [e for e in cap_logs if e.get("event") == "panoramic_part_of_rejected"]
    assert len(rejection_events) == 0, "Valid part_of should not be rejected"
    assert applied == 1
