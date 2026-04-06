"""Composite FK integrity tests — cross-workspace references must be rejected."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
async def test_entity_cannot_reference_type_from_different_workspace(session_ws_a, session_ws_b):
    """Creating an entity in workspace A with a type from workspace B should fail."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()
    ws_b_id = (await session_ws_b.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    # Create entity type in workspace B
    type_id = uuid.uuid4()
    await session_ws_b.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, 'person', 'Person')"
        ),
        {"id": type_id, "ws": ws_b_id},
    )
    await session_ws_b.flush()

    # Try to create entity in workspace A referencing type from workspace B
    with pytest.raises(IntegrityError):
        await session_ws_a.execute(
            text(
                "INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'Cross-WS')"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "tid": type_id},
        )
        await session_ws_a.flush()


@pytest.mark.integration
async def test_claim_cannot_reference_entity_from_different_workspace(session_ws_a, session_ws_b):
    """Creating a claim in workspace A with an entity from workspace B should fail."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()
    ws_b_id = (await session_ws_b.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    # Create entity type and entity in workspace B
    type_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    await session_ws_b.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_b_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    await session_ws_b.execute(
        text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
        {"id": entity_id, "ws": ws_b_id, "tid": type_id},
    )
    await session_ws_b.flush()

    # Try to create claim in workspace A referencing entity from workspace B
    with pytest.raises(IntegrityError):
        await session_ws_a.execute(
            text(
                "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value) "
                "VALUES (:id, :ws, :eid, 'test', '\"test\"'::jsonb)"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "eid": entity_id},
        )
        await session_ws_a.flush()


@pytest.mark.integration
async def test_relation_cannot_reference_entities_from_different_workspace(session_ws_a, session_ws_b):
    """Creating a relation in workspace A referencing entities from workspace B should fail."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()
    ws_b_id = (await session_ws_b.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    # Create entities in workspace B
    type_id = uuid.uuid4()
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    await session_ws_b.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_b_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    for eid in (e1, e2):
        await session_ws_b.execute(
            text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
            {"id": eid, "ws": ws_b_id, "tid": type_id},
        )
    await session_ws_b.flush()

    # Try to create relation in workspace A referencing entities from workspace B
    with pytest.raises(IntegrityError):
        await session_ws_a.execute(
            text(
                "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type) "
                "VALUES (:id, :ws, :e1, :e2, 'test')"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "e1": e1, "e2": e2},
        )
        await session_ws_a.flush()
