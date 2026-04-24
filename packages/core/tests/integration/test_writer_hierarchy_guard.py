"""Integration test: writer.py hierarchy guard.

Verifies that atomic_write skips invalid part_of relations (with log warning)
while still writing valid ones; the overall extraction run does not fail.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
import structlog.testing

from alayaos_core.extraction.schemas import ExtractedEntity, ExtractedRelation, ExtractionResult
from alayaos_core.extraction.writer import atomic_write
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.entity_type import EntityTypeRepository
from alayaos_core.repositories.event import EventRepository

pytestmark = pytest.mark.integration


async def _get_entity_type_id(db_session, workspace_id: uuid.UUID, slug: str) -> uuid.UUID:
    et_repo = EntityTypeRepository(db_session, workspace_id)
    et = await et_repo.get_by_slug(workspace_id, slug)
    assert et is not None, f"Entity type '{slug}' not seeded"
    return et.id


@pytest.mark.asyncio
async def test_writer_skips_invalid_part_of_and_continues(workspace, db_session):
    """Writer skips tier-inverted part_of relations, logs warning, doesn't fail the run."""
    ws_id = workspace.id

    # Seed two entities: project and task
    project_type_id = await _get_entity_type_id(db_session, ws_id, "project")
    task_type_id = await _get_entity_type_id(db_session, ws_id, "task")

    entity_repo = EntityRepository(db_session, ws_id)
    project = await entity_repo.create(workspace_id=ws_id, entity_type_id=project_type_id, name="ProjectAlpha")
    task = await entity_repo.create(workspace_id=ws_id, entity_type_id=task_type_id, name="TaskBeta")
    await db_session.flush()

    # Build ExtractionResult with:
    #   - one valid relation: task → project (part_of, ok)
    #   - one invalid relation: project → task (part_of, inverted tier)
    extraction_result = ExtractionResult(
        entities=[
            ExtractedEntity(name="ProjectAlpha", entity_type="project"),
            ExtractedEntity(name="TaskBeta", entity_type="task"),
        ],
        relations=[
            ExtractedRelation(
                source_entity="TaskBeta",
                target_entity="ProjectAlpha",
                relation_type="part_of",
            ),
            ExtractedRelation(
                source_entity="ProjectAlpha",
                target_entity="TaskBeta",
                relation_type="part_of",
            ),
        ],
        claims=[],
    )

    # Build real event + mock run
    event_repo = EventRepository(db_session, ws_id)
    event = await event_repo.create(
        workspace_id=ws_id,
        source_type="test",
        source_id=f"writer-hierarchy-{uuid.uuid4()}",
        content={"text": "TaskBeta is part of ProjectAlpha."},
    )

    run = MagicMock()
    run.id = None  # avoid FK constraint on extraction_run_id
    run.resolver_decisions = []

    # We skip resolve_batch by passing entity_name_to_id directly
    entity_name_to_id = {
        "ProjectAlpha": project.id,
        "TaskBeta": task.id,
    }

    # Mock run_repo.update_counters and clear_raw_extraction
    run_repo_mock = AsyncMock()
    run_repo_mock.update_counters = AsyncMock()
    run_repo_mock.clear_raw_extraction = AsyncMock()

    with (
        structlog.testing.capture_logs() as cap_logs,
        patch(
            "alayaos_core.extraction.writer.ExtractionRunRepository",
            return_value=run_repo_mock,
        ),
    ):
        counters = await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=db_session,
            llm=AsyncMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=None,
        )

    # Only the valid relation should be created
    assert counters["relations_created"] == 1, (
        f"Expected 1 relation created (valid only), got {counters['relations_created']}"
    )

    # Check that writer_part_of_rejected was logged
    rejection_events = [e for e in cap_logs if e.get("event") == "writer_part_of_rejected"]
    assert len(rejection_events) == 1, f"Expected 1 writer_part_of_rejected log event, got {len(rejection_events)}"
