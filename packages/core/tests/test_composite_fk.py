"""Composite FK integrity tests — cross-workspace references must be rejected.

Uses a single session per test so all parent rows are visible in the same
transaction (no cross-session lock contention).  Each test commits nothing —
the session fixture rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
async def test_entity_cannot_reference_type_from_different_workspace(session):
    """Creating an entity in workspace A with a type from workspace B should fail."""
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    type_id = uuid.uuid4()

    # Create both workspaces
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-A', :slug)"),
        {"id": ws_a_id, "slug": f"fk-test-a-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-B', :slug)"),
        {"id": ws_b_id, "slug": f"fk-test-b-{uuid.uuid4().hex[:8]}"},
    )

    # Create entity type in workspace B (same transaction — visible immediately)
    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name)"
            " VALUES (:id, :ws, :slug, 'Person')"
        ),
        {"id": type_id, "ws": ws_b_id, "slug": f"person-{uuid.uuid4().hex[:8]}"},
    )

    # Try to create entity in workspace A referencing type from workspace B.
    # Composite FK (workspace_id, entity_type_id) should reject this.
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'Cross-WS')"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "tid": type_id},
        )
        await session.flush()


@pytest.mark.integration
async def test_claim_cannot_reference_entity_from_different_workspace(session):
    """Creating a claim in workspace A with an entity from workspace B should fail."""
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    type_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-A', :slug)"),
        {"id": ws_a_id, "slug": f"fk-test-a-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-B', :slug)"),
        {"id": ws_b_id, "slug": f"fk-test-b-{uuid.uuid4().hex[:8]}"},
    )

    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_b_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
        {"id": entity_id, "ws": ws_b_id, "tid": type_id},
    )

    # Try to create claim in workspace A referencing entity from workspace B.
    # Composite FK (workspace_id, entity_id) should reject this.
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value)"
                " VALUES (:id, :ws, :eid, 'test', '\"test\"'::jsonb)"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "eid": entity_id},
        )
        await session.flush()


@pytest.mark.integration
async def test_relation_cannot_reference_entities_from_different_workspace(session):
    """Creating a relation in workspace A referencing entities from workspace B should fail."""
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    type_id = uuid.uuid4()
    e1, e2 = uuid.uuid4(), uuid.uuid4()

    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-A', :slug)"),
        {"id": ws_a_id, "slug": f"fk-test-a-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-B', :slug)"),
        {"id": ws_b_id, "slug": f"fk-test-b-{uuid.uuid4().hex[:8]}"},
    )

    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_b_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    for eid in (e1, e2):
        await session.execute(
            text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
            {"id": eid, "ws": ws_b_id, "tid": type_id},
        )

    # Try to create relation in workspace A referencing entities from workspace B.
    # Composite FK (workspace_id, source_entity_id) should reject this.
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type)"
                " VALUES (:id, :ws, :e1, :e2, 'test')"
            ),
            {"id": uuid.uuid4(), "ws": ws_a_id, "e1": e1, "e2": e2},
        )
        await session.flush()


@pytest.mark.integration
async def test_claim_source_composite_fk_rejects_cross_workspace(session):
    """Inserting claim_source with (ws_B, claim_A.id) must fail via composite FK."""
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    type_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    event_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    # Create two workspaces
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-A', :slug)"),
        {"id": ws_a_id, "slug": f"fk-cs-a-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'WS-B', :slug)"),
        {"id": ws_b_id, "slug": f"fk-cs-b-{uuid.uuid4().hex[:8]}"},
    )

    # Build the FK chain in ws_a
    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    await session.execute(
        text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
        {"id": entity_id, "ws": ws_a_id, "tid": type_id},
    )
    await session.execute(
        text(
            "INSERT INTO l0_events (id, workspace_id, source_type, source_id, content) "
            "VALUES (:id, :ws, 'test', :src, '{}'::jsonb)"
        ),
        {"id": event_id, "ws": ws_a_id, "src": str(uuid.uuid4())},
    )
    await session.execute(
        text(
            "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value) "
            "VALUES (:id, :ws, :eid, 'test', '\"v\"'::jsonb)"
        ),
        {"id": claim_id, "ws": ws_a_id, "eid": entity_id},
    )

    # Try to insert claim_source with ws_b referencing claim from ws_a.
    # Composite FK (workspace_id, claim_id) → l2_claims should reject this.
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO claim_sources (id, workspace_id, claim_id, event_id) "
                "VALUES (:id, :ws_b, :cid, :eid)"
            ),
            {"id": uuid.uuid4(), "ws_b": ws_b_id, "cid": claim_id, "eid": event_id},
        )
        await session.flush()
