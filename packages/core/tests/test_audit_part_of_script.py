"""Tests for scripts/audit_part_of_hierarchy.py.

Seeds valid + inverted part_of relations directly via SQL (bypassing repo guards),
then calls the audit script via subprocess to verify it reports violations correctly.

Marked integration because it requires a running testcontainer postgres.
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixture: isolated session on superuser engine to bypass RLS + repo guards
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def superuser_session(engine_superuser):
    """Per-test superuser session (no RLS) for direct SQL seeding."""
    session_factory = async_sessionmaker(engine_superuser, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        yield sess
        await sess.rollback()


# ---------------------------------------------------------------------------
# Helper: insert a relation directly (bypassing RelationRepository guards)
# ---------------------------------------------------------------------------


async def _direct_insert_relation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    relation_type: str = "part_of",
) -> uuid.UUID:
    rel_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO l1_relations
                (id, workspace_id, source_entity_id, target_entity_id, relation_type, confidence)
            VALUES
                (:id, :workspace_id, :source_entity_id, :target_entity_id, :relation_type, 1.0)
            """
        ),
        {
            "id": rel_id,
            "workspace_id": workspace_id,
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "relation_type": relation_type,
        },
    )
    return rel_id


# ---------------------------------------------------------------------------
# Helper: seed a minimal workspace + entity types + entities
# ---------------------------------------------------------------------------


async def _seed_workspace_and_entities(
    session: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed workspace, task and project entity types + two task and two project entities.

    Returns: (workspace_id, task_entity_id, project_entity_id, project2_entity_id, task2_entity_id)
    """
    ws_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": ws_id, "name": f"audit-test-ws-{ws_id.hex[:6]}", "slug": f"audit-{ws_id.hex[:8]}"},
    )

    # Entity types
    task_et_id = uuid.uuid4()
    project_et_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES "
            "(:id, :ws, 'task', 'Task')"
        ),
        {"id": task_et_id, "ws": ws_id},
    )
    await session.execute(
        text(
            "INSERT INTO entity_type_definitions (id, workspace_id, slug, display_name) VALUES "
            "(:id, :ws, 'project', 'Project')"
        ),
        {"id": project_et_id, "ws": ws_id},
    )

    # Entities
    task_id = uuid.uuid4()
    task2_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project2_id = uuid.uuid4()

    for eid, et_id, name in [
        (task_id, task_et_id, "Task-A"),
        (task2_id, task_et_id, "Task-B"),
        (project_id, project_et_id, "Project-A"),
        (project2_id, project_et_id, "Project-B"),
    ]:
        await session.execute(
            text("INSERT INTO l1_entities (id, workspace_id, entity_type_id, name) VALUES (:id, :ws, :et_id, :name)"),
            {"id": eid, "ws": ws_id, "et_id": et_id, "name": name},
        )

    return ws_id, task_id, project_id, project2_id, task2_id


def test_audit_script_exit_code_when_violations_found(monkeypatch):
    """main() exits with code 1 when _run_audit returns a non-zero violation count."""
    scripts_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import audit_part_of_hierarchy as script

    # Monkeypatch _run_audit to return 2 violations synchronously via a coroutine
    async def _fake_run_audit(database_url, workspace_id, sample_size):
        return 2

    monkeypatch.setattr(script, "_run_audit", _fake_run_audit)
    monkeypatch.setenv("ALAYA_DATABASE_URL", "postgresql+asyncpg://fake/fake")
    monkeypatch.setattr(sys, "argv", ["audit_part_of_hierarchy.py", "--workspace-id", str(uuid.uuid4())])

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_audit_logic_directly(migrated_container, engine_superuser):
    """Test audit logic directly (without subprocess) by calling _run_audit.

    Uses a standalone committed transaction for seeding so that _run_audit (which
    opens its own connection) can see the data. A try/finally ensures cleanup even
    if the assertion fails — rows are deleted by workspace_id cascade or explicit DELETE.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(engine_superuser, expire_on_commit=False)

    # Seed data in a standalone committed transaction
    ws_id = uuid.uuid4()
    async with session_factory() as seed_sess, seed_sess.begin():
        ws_id, task_id, project_id, project2_id, task2_id = await _seed_workspace_and_entities(seed_sess)
        await _direct_insert_relation(seed_sess, ws_id, task_id, project_id, "part_of")
        await _direct_insert_relation(seed_sess, ws_id, task2_id, project2_id, "part_of")
        await _direct_insert_relation(seed_sess, ws_id, project_id, task_id, "part_of")
        await _direct_insert_relation(seed_sess, ws_id, project2_id, task2_id, "part_of")
    # Transaction committed here — _run_audit will see the rows

    # Import the audit function directly
    scripts_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from audit_part_of_hierarchy import _run_audit

    db_url = migrated_container.get_connection_url()
    try:
        count = await _run_audit(db_url, ws_id, 20)
        assert count == 2, f"Expected 2 violations, got {count}"
    finally:
        # Clean up seeded rows so they don't leak into subsequent tests.
        # Delete in FK-dependency order: relations → entities → entity_type_definitions → workspace.
        async with session_factory() as cleanup_sess, cleanup_sess.begin():
            await cleanup_sess.execute(
                text("DELETE FROM l1_relations WHERE workspace_id = :ws_id"),
                {"ws_id": ws_id},
            )
            await cleanup_sess.execute(
                text("DELETE FROM l1_entities WHERE workspace_id = :ws_id"),
                {"ws_id": ws_id},
            )
            await cleanup_sess.execute(
                text("DELETE FROM entity_type_definitions WHERE workspace_id = :ws_id"),
                {"ws_id": ws_id},
            )
            await cleanup_sess.execute(
                text("DELETE FROM workspaces WHERE id = :ws_id"),
                {"ws_id": ws_id},
            )
