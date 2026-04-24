"""Unit matrix for RelationRepository hierarchy enforcement (Sprint 2).

Tests use the `workspace` fixture (integration — requires testcontainers postgres).
Marked with `integration` so they run under `pytest -m integration`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import structlog.testing
from sqlalchemy import text

from alayaos_core import config
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.entity_type import EntityTypeRepository
from alayaos_core.repositories.errors import HierarchyViolationError
from alayaos_core.repositories.relation import RelationRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_entity_type_id(db_session: AsyncSession, workspace_id: uuid.UUID, slug: str) -> uuid.UUID:
    """Fetch seeded entity type ID by slug."""
    et_repo = EntityTypeRepository(db_session, workspace_id)
    et = await et_repo.get_by_slug(workspace_id, slug)
    assert et is not None, f"Entity type '{slug}' not seeded"
    return et.id


async def _create_entity(
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    slug: str,
    name: str | None = None,
) -> uuid.UUID:
    """Create an entity of the given type slug, return its ID."""
    et_id = await _get_entity_type_id(db_session, workspace_id, slug)
    entity_repo = EntityRepository(db_session, workspace_id)
    entity = await entity_repo.create(
        workspace_id=workspace_id,
        entity_type_id=et_id,
        name=name or f"{slug}-{uuid.uuid4().hex[:6]}",
    )
    return entity.id


# ---------------------------------------------------------------------------
# ALAYA_PART_OF_STRICT mode matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["strict", "warn", "off"])
@pytest.mark.parametrize("scenario", ["valid", "self_ref", "tier_inversion"])
@pytest.mark.asyncio
async def test_validate_part_of_tier_respects_strict_warn_off_modes(
    workspace,
    db_session,
    monkeypatch,
    mode: str,
    scenario: str,
) -> None:
    monkeypatch.setenv("ALAYA_PART_OF_STRICT", mode)
    config.get_settings.cache_clear()

    task_id = await _create_entity(db_session, workspace.id, "task")
    project_id = await _create_entity(db_session, workspace.id, "project")

    if scenario == "valid":
        source_id = task_id
        target_id = project_id
    elif scenario == "self_ref":
        source_id = task_id
        target_id = task_id
    else:
        source_id = project_id
        target_id = task_id

    repo = RelationRepository(db_session, workspace.id)

    with structlog.testing.capture_logs() as logs:
        if scenario == "self_ref":
            with pytest.raises(HierarchyViolationError, match="self-referential"):
                await repo.create(
                    workspace_id=workspace.id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="part_of",
                )
        elif scenario == "tier_inversion" and mode == "strict":
            with pytest.raises(HierarchyViolationError, match="part_of"):
                await repo.create(
                    workspace_id=workspace.id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="part_of",
                )
        else:
            rel = await repo.create(
                workspace_id=workspace.id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type="part_of",
            )
            assert rel is not None

    warning_events = [entry for entry in logs if entry["event"] == "part_of.tier_violation"]
    if scenario == "tier_inversion" and mode == "warn":
        assert len(warning_events) == 1
        assert warning_events[0]["mode"] == "warn"
    else:
        assert warning_events == []

    result = await db_session.execute(
        text("SELECT COUNT(*) FROM l1_relations WHERE workspace_id = :wid"),
        {"wid": workspace.id},
    )
    count = result.scalar()
    expected_count = 1 if scenario == "valid" or (scenario == "tier_inversion" and mode in {"warn", "off"}) else 0
    assert count == expected_count

    config.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Task → project (valid: task rank=1 < project rank=2) — should succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_to_project_part_of_succeeds(workspace, db_session):
    task_id = await _create_entity(db_session, workspace.id, "task")
    project_id = await _create_entity(db_session, workspace.id, "project")

    repo = RelationRepository(db_session, workspace.id)
    rel = await repo.create(
        workspace_id=workspace.id,
        source_entity_id=task_id,
        target_entity_id=project_id,
        relation_type="part_of",
    )
    assert rel is not None
    assert rel.relation_type == "part_of"


# ---------------------------------------------------------------------------
# Project → task (invalid: project rank=2 >= task rank=1) — should raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_to_task_part_of_raises(workspace, db_session):
    project_id = await _create_entity(db_session, workspace.id, "project")
    task_id = await _create_entity(db_session, workspace.id, "task")

    repo = RelationRepository(db_session, workspace.id)
    with pytest.raises(HierarchyViolationError, match="part_of"):
        await repo.create(
            workspace_id=workspace.id,
            source_entity_id=project_id,
            target_entity_id=task_id,
            relation_type="part_of",
        )


# ---------------------------------------------------------------------------
# Self-reference: task → same task, part_of — self-ref check fires first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_to_task_part_of_raises_self_ref(workspace, db_session):
    task_id = await _create_entity(db_session, workspace.id, "task")

    repo = RelationRepository(db_session, workspace.id)
    with pytest.raises(HierarchyViolationError, match="self-referential"):
        await repo.create(
            workspace_id=workspace.id,
            source_entity_id=task_id,
            target_entity_id=task_id,
            relation_type="part_of",
        )


# ---------------------------------------------------------------------------
# Self-reference: person → same person, part_of — person not tiered, self-ref fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_to_person_part_of_raises_self_ref(workspace, db_session):
    person_id = await _create_entity(db_session, workspace.id, "person")

    repo = RelationRepository(db_session, workspace.id)
    with pytest.raises(HierarchyViolationError, match="self-referential"):
        await repo.create(
            workspace_id=workspace.id,
            source_entity_id=person_id,
            target_entity_id=person_id,
            relation_type="part_of",
        )


# ---------------------------------------------------------------------------
# Self-reference with non-part_of relation type (reports_to)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_reports_to_self_raises(workspace, db_session):
    person_id = await _create_entity(db_session, workspace.id, "person")

    repo = RelationRepository(db_session, workspace.id)
    with pytest.raises(HierarchyViolationError, match="self-referential"):
        await repo.create(
            workspace_id=workspace.id,
            source_entity_id=person_id,
            target_entity_id=person_id,
            relation_type="reports_to",
        )


# ---------------------------------------------------------------------------
# Different ids, non-part_of relation — should pass (tier unchecked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_reports_to_project_passes(workspace, db_session):
    task_id = await _create_entity(db_session, workspace.id, "task")
    project_id = await _create_entity(db_session, workspace.id, "project")

    repo = RelationRepository(db_session, workspace.id)
    # reports_to is not part_of → no tier check
    rel = await repo.create(
        workspace_id=workspace.id,
        source_entity_id=task_id,
        target_entity_id=project_id,
        relation_type="reports_to",
    )
    assert rel is not None


# ---------------------------------------------------------------------------
# create_batch: all valid → both land
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_batch_all_valid_lands(workspace, db_session):
    task1_id = await _create_entity(db_session, workspace.id, "task", name="task-alpha")
    task2_id = await _create_entity(db_session, workspace.id, "task", name="task-beta")
    project_id = await _create_entity(db_session, workspace.id, "project")

    repo = RelationRepository(db_session, workspace.id)
    rows = [
        {"source_entity_id": task1_id, "target_entity_id": project_id, "relation_type": "part_of"},
        {"source_entity_id": task2_id, "target_entity_id": project_id, "relation_type": "part_of"},
    ]
    created = await repo.create_batch(workspace.id, rows)
    assert len(created) == 2


# ---------------------------------------------------------------------------
# create_batch: one valid + one inverted → raises BEFORE any session.add
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_batch_one_invalid_raises_before_any_insert(workspace, db_session):
    task_id = await _create_entity(db_session, workspace.id, "task")
    project_id = await _create_entity(db_session, workspace.id, "project")

    repo = RelationRepository(db_session, workspace.id)
    rows = [
        # Valid row first
        {"source_entity_id": task_id, "target_entity_id": project_id, "relation_type": "part_of"},
        # Invalid: project → task (inverted tier)
        {"source_entity_id": project_id, "target_entity_id": task_id, "relation_type": "part_of"},
    ]

    with pytest.raises(HierarchyViolationError):
        await repo.create_batch(workspace.id, rows)

    # Verify no relations were persisted (batch fails atomically)
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM l1_relations WHERE workspace_id = :wid"),
        {"wid": workspace.id},
    )
    count = result.scalar()
    assert count == 0, f"Expected 0 relations after failed batch, got {count}"
