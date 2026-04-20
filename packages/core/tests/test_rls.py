"""Parametrized RLS isolation tests for ALL workspace-scoped tables."""

import uuid

import pytest
from sqlalchemy import text

# List ALL models that have workspace_id (14 tables from the RLS matrix)
# We test by inserting a row via session_ws_a and querying via session_ws_b
ALL_TENANT_TABLES = [
    "l0_events",
    "entity_type_definitions",
    "predicate_definitions",
    "l1_entities",
    "entity_external_ids",
    "l1_relations",
    "l2_claims",
    "l3_tree_nodes",
    "vector_chunks",
    # api_keys is excluded: migration 002 uses NO FORCE ROW LEVEL SECURITY on this
    # table, so the table owner (test user) bypasses RLS by design.
    "workspace_members",
    "access_groups",
    "resource_grants",
    "audit_log",
]

# Minimal insert SQL for each table (just enough to satisfy NOT NULL and FK constraints)
# For tables that need FK deps, we create them in the same workspace first.


@pytest.mark.integration
@pytest.mark.parametrize("table_name", ALL_TENANT_TABLES)
async def test_workspace_isolation(table_name, session_ws_a, session_ws_b):
    """Insert via session_ws_a → query via session_ws_b → expect 0 results."""
    # This is a template — each table needs specific INSERT logic
    # For the parametrized test, we use raw SQL with table-specific minimal data

    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    # Insert a row into the table via workspace A
    row_id = uuid.uuid4()

    # Table-specific insert logic
    if table_name == "l0_events":
        await session_ws_a.execute(
            text(
                "INSERT INTO l0_events (id, workspace_id, source_type, source_id, content) "
                "VALUES (:id, :ws, 'test', :src, '{}'::jsonb)"
            ),
            {"id": row_id, "ws": ws_a_id, "src": str(uuid.uuid4())},
        )
    elif table_name == "entity_type_definitions":
        await session_ws_a.execute(
            text(
                "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) "
                "VALUES (:id, :ws, :slug, 'Test')"
            ),
            {"id": row_id, "ws": ws_a_id, "slug": f"test-{uuid.uuid4().hex[:8]}"},
        )
    elif table_name == "predicate_definitions":
        await session_ws_a.execute(
            text(
                "INSERT INTO predicate_definitions (id, workspace_id, slug, display_name) "
                "VALUES (:id, :ws, :slug, 'Test')"
            ),
            {"id": row_id, "ws": ws_a_id, "slug": f"test-{uuid.uuid4().hex[:8]}"},
        )
    elif table_name == "l1_entities":
        # Need entity_type first
        type_id = uuid.uuid4()
        await session_ws_a.execute(
            text(
                "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) "
                "VALUES (:id, :ws, :slug, 'Test')"
            ),
            {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
        )
        await session_ws_a.execute(
            text(
                "INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) "
                "VALUES (:id, :ws, :type_id, 'Test Entity')"
            ),
            {"id": row_id, "ws": ws_a_id, "type_id": type_id},
        )
    elif table_name == "entity_external_ids":
        type_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        await session_ws_a.execute(
            text(
                "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) "
                "VALUES (:id, :ws, :slug, 'Test')"
            ),
            {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
        )
        await session_ws_a.execute(
            text(
                "INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :type_id, 'Test')"
            ),
            {"id": entity_id, "ws": ws_a_id, "type_id": type_id},
        )
        await session_ws_a.execute(
            text(
                "INSERT INTO entity_external_ids (id, workspace_id, entity_id, source_type, external_id, created_at) "
                "VALUES (:id, :ws, :eid, 'test', :ext, now())"
            ),
            {"id": row_id, "ws": ws_a_id, "eid": entity_id, "ext": str(uuid.uuid4())},
        )
    elif table_name == "api_keys":
        await session_ws_a.execute(
            text(
                "INSERT INTO api_keys (id, workspace_id, name, key_prefix, key_hash) "
                "VALUES (:id, :ws, 'Test', :prefix, 'hash')"
            ),
            {"id": row_id, "ws": ws_a_id, "prefix": f"ak_{uuid.uuid4().hex[:8]}"},
        )
    elif table_name == "audit_log":
        await session_ws_a.execute(
            text(
                "INSERT INTO audit_log (id, workspace_id, actor_type, actor_id, action, resource_type) "
                "VALUES (:id, :ws, 'test', 'test', 'test.action', 'test')"
            ),
            {"id": row_id, "ws": ws_a_id},
        )
    elif table_name == "workspace_members":
        await session_ws_a.execute(
            text("INSERT INTO workspace_members (id, workspace_id, user_id) VALUES (:id, :ws, :uid)"),
            {"id": row_id, "ws": ws_a_id, "uid": str(uuid.uuid4())},
        )
    elif table_name == "access_groups":
        await session_ws_a.execute(
            text("INSERT INTO access_groups (id, workspace_id, name) VALUES (:id, :ws, :name)"),
            {"id": row_id, "ws": ws_a_id, "name": f"group-{uuid.uuid4().hex[:8]}"},
        )
    elif table_name == "resource_grants":
        await session_ws_a.execute(
            text(
                "INSERT INTO resource_grants (id, workspace_id, grantee_type, grantee_id, resource_type, permission) "
                "VALUES (:id, :ws, 'member', :gid, 'entity', 'read')"
            ),
            {"id": row_id, "ws": ws_a_id, "gid": uuid.uuid4()},
        )
    elif table_name in ("l1_relations", "l2_claims", "l3_tree_nodes", "vector_chunks"):
        # These need more complex FK chains — test with raw SQL
        if table_name == "l3_tree_nodes":
            await session_ws_a.execute(
                text(
                    "INSERT INTO l3_tree_nodes (id, workspace_id, path, node_type) VALUES (:id, :ws, :path, 'section')"
                ),
                {"id": row_id, "ws": ws_a_id, "path": f"/test/{uuid.uuid4().hex[:8]}"},
            )
        elif table_name == "vector_chunks":
            await session_ws_a.execute(
                text(
                    "INSERT INTO vector_chunks (id, workspace_id, source_type, source_id, chunk_index, content, created_at) "
                    "VALUES (:id, :ws, 'test', :src, 0, 'test content', now())"
                ),
                {"id": row_id, "ws": ws_a_id, "src": uuid.uuid4()},
            )
        elif table_name == "l1_relations":
            # Need two entities
            type_id = uuid.uuid4()
            e1, e2 = uuid.uuid4(), uuid.uuid4()
            await session_ws_a.execute(
                text(
                    "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
                ),
                {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
            )
            for eid in (e1, e2):
                await session_ws_a.execute(
                    text(
                        "INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"
                    ),
                    {"id": eid, "ws": ws_a_id, "tid": type_id},
                )
            await session_ws_a.execute(
                text(
                    "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type) "
                    "VALUES (:id, :ws, :e1, :e2, 'test')"
                ),
                {"id": row_id, "ws": ws_a_id, "e1": e1, "e2": e2},
            )
        elif table_name == "l2_claims":
            type_id = uuid.uuid4()
            entity_id = uuid.uuid4()
            await session_ws_a.execute(
                text(
                    "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
                ),
                {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
            )
            await session_ws_a.execute(
                text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
                {"id": entity_id, "ws": ws_a_id, "tid": type_id},
            )
            await session_ws_a.execute(
                text(
                    "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value) "
                    "VALUES (:id, :ws, :eid, 'test', '\"test\"'::jsonb)"
                ),
                {"id": row_id, "ws": ws_a_id, "eid": entity_id},
            )

    await session_ws_a.flush()

    # Verify row exists in ws_a
    result_a = await session_ws_a.execute(
        text(f"SELECT count(*) FROM {table_name} WHERE id = :id"),
        {"id": row_id},
    )
    assert result_a.scalar() == 1, f"Row not found in workspace A for {table_name}"

    # Query via workspace B — should find 0 rows
    result_b = await session_ws_b.execute(
        text(f"SELECT count(*) FROM {table_name} WHERE id = :id"),
        {"id": row_id},
    )
    assert result_b.scalar() == 0, f"RLS leak: workspace B can see {table_name} row from workspace A"


# ---------------------------------------------------------------------------
# RLS isolation tests for migration-007 join tables
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_claim_sources_rls_isolation(session_ws_a, session_ws_b):
    """claim_sources inserted in ws A are invisible to ws B."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    # Create parent claim (and its FK chain) in ws A
    type_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    event_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    row_id = uuid.uuid4()

    await session_ws_a.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    await session_ws_a.execute(
        text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
        {"id": entity_id, "ws": ws_a_id, "tid": type_id},
    )
    await session_ws_a.execute(
        text(
            "INSERT INTO l0_events (id, workspace_id, source_type, source_id, content) "
            "VALUES (:id, :ws, 'test', :src, '{}'::jsonb)"
        ),
        {"id": event_id, "ws": ws_a_id, "src": str(uuid.uuid4())},
    )
    await session_ws_a.execute(
        text(
            "INSERT INTO l2_claims (id, workspace_id, entity_id, predicate, value) "
            "VALUES (:id, :ws, :eid, 'test', '\"v\"'::jsonb)"
        ),
        {"id": claim_id, "ws": ws_a_id, "eid": entity_id},
    )
    await session_ws_a.execute(
        text("INSERT INTO claim_sources (id, workspace_id, claim_id, event_id) VALUES (:id, :ws, :cid, :eid)"),
        {"id": row_id, "ws": ws_a_id, "cid": claim_id, "eid": event_id},
    )
    await session_ws_a.flush()

    result_a = await session_ws_a.execute(
        text("SELECT count(*) FROM claim_sources WHERE id = :id"),
        {"id": row_id},
    )
    assert result_a.scalar() == 1, "claim_source not found in workspace A"

    result_b = await session_ws_b.execute(
        text("SELECT count(*) FROM claim_sources WHERE id = :id"),
        {"id": row_id},
    )
    assert result_b.scalar() == 0, "RLS leak: workspace B can see claim_sources row from workspace A"


@pytest.mark.integration
async def test_relation_sources_rls_isolation(session_ws_a, session_ws_b):
    """relation_sources inserted in ws A are invisible to ws B."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    type_id = uuid.uuid4()
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    event_id = uuid.uuid4()
    relation_id = uuid.uuid4()
    row_id = uuid.uuid4()

    await session_ws_a.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES (:id, :ws, :slug, 'T')"
        ),
        {"id": type_id, "ws": ws_a_id, "slug": f"et-{uuid.uuid4().hex[:8]}"},
    )
    for eid in (e1, e2):
        await session_ws_a.execute(
            text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :tid, 'E')"),
            {"id": eid, "ws": ws_a_id, "tid": type_id},
        )
    await session_ws_a.execute(
        text(
            "INSERT INTO l0_events (id, workspace_id, source_type, source_id, content) "
            "VALUES (:id, :ws, 'test', :src, '{}'::jsonb)"
        ),
        {"id": event_id, "ws": ws_a_id, "src": str(uuid.uuid4())},
    )
    await session_ws_a.execute(
        text(
            "INSERT INTO l1_relations (id, workspace_id, source_entity_id, target_entity_id, relation_type) "
            "VALUES (:id, :ws, :e1, :e2, 'test')"
        ),
        {"id": relation_id, "ws": ws_a_id, "e1": e1, "e2": e2},
    )
    await session_ws_a.execute(
        text("INSERT INTO relation_sources (id, workspace_id, relation_id, event_id) VALUES (:id, :ws, :rid, :eid)"),
        {"id": row_id, "ws": ws_a_id, "rid": relation_id, "eid": event_id},
    )
    await session_ws_a.flush()

    result_a = await session_ws_a.execute(
        text("SELECT count(*) FROM relation_sources WHERE id = :id"),
        {"id": row_id},
    )
    assert result_a.scalar() == 1, "relation_source not found in workspace A"

    result_b = await session_ws_b.execute(
        text("SELECT count(*) FROM relation_sources WHERE id = :id"),
        {"id": row_id},
    )
    assert result_b.scalar() == 0, "RLS leak: workspace B can see relation_sources row from workspace A"


@pytest.mark.integration
async def test_access_group_members_rls_isolation(session_ws_a, session_ws_b):
    """access_group_members inserted in ws A are invisible to ws B."""
    ws_a_id = (await session_ws_a.execute(text("SELECT current_setting('app.workspace_id', true)"))).scalar()

    group_id = uuid.uuid4()
    member_id = uuid.uuid4()
    row_id = uuid.uuid4()

    await session_ws_a.execute(
        text("INSERT INTO access_groups (id, workspace_id, name) VALUES (:id, :ws, :name)"),
        {"id": group_id, "ws": ws_a_id, "name": f"group-{uuid.uuid4().hex[:8]}"},
    )
    await session_ws_a.execute(
        text("INSERT INTO workspace_members (id, workspace_id, user_id) VALUES (:id, :ws, :uid)"),
        {"id": member_id, "ws": ws_a_id, "uid": str(uuid.uuid4())},
    )
    await session_ws_a.execute(
        text("INSERT INTO access_group_members (id, workspace_id, group_id, member_id) VALUES (:id, :ws, :gid, :mid)"),
        {"id": row_id, "ws": ws_a_id, "gid": group_id, "mid": member_id},
    )
    await session_ws_a.flush()

    result_a = await session_ws_a.execute(
        text("SELECT count(*) FROM access_group_members WHERE id = :id"),
        {"id": row_id},
    )
    assert result_a.scalar() == 1, "access_group_member not found in workspace A"

    result_b = await session_ws_b.execute(
        text("SELECT count(*) FROM access_group_members WHERE id = :id"),
        {"id": row_id},
    )
    assert result_b.scalar() == 0, "RLS leak: workspace B can see access_group_members row from workspace A"
