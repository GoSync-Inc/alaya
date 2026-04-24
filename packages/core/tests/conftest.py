"""Integration test fixtures — testcontainers + alembic + app-role RLS harness.

The session-level pg_container fixture spins an ephemeral pgvector postgres
container per test session. alembic upgrade head is the sole schema source —
Base.metadata.create_all is never used. A non-superuser alaya_app role is
provisioned so that RLS negative tests are valid; the superuser bypasses RLS.
"""

import re
import uuid
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from alayaos_core.services import workspace as workspace_service
from alembic import command as alembic_command

# ---------------------------------------------------------------------------
# Task 2a: pg_container — session-scoped sync fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer]:
    """Spin up an ephemeral pgvector postgres container for the test session."""
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as container:
        # Safety guard: assert container is running and URL uses asyncpg
        assert container._container is not None, "testcontainers container did not start"
        url = container.get_connection_url()
        assert re.match(r"^postgresql\+asyncpg://", url), f"Unexpected URL scheme: {url}"
        yield container


# ---------------------------------------------------------------------------
# Task 2b+2c: migrated_container — session-scoped sync fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_container(pg_container: PostgresContainer) -> PostgresContainer:
    """Run alembic upgrade head and provision the alaya_app role.

    Uses pytest.MonkeyPatch() context manager to set ALAYA_DATABASE_URL
    so alembic env.py (which reads Settings) picks up the container URL.
    Connections are synchronous (psycopg2 fallback via +psycopg2 URL rewrite)
    because alembic runs synchronously in the default configuration.
    """
    # alembic env.py uses asyncio.run() internally so it can handle the asyncpg URL directly.
    # We monkeypatch ALAYA_DATABASE_URL so Settings (read inside env.py) picks up the container URL.
    container_url = pg_container.get_connection_url()

    # Task 2b: monkeypatch ALAYA_DATABASE_URL so Settings picks it up in alembic env.py
    mp = pytest.MonkeyPatch()
    with mp.context() as m:
        m.setenv("ALAYA_DATABASE_URL", container_url)
        cfg = AlembicConfig("alembic.ini")
        alembic_command.upgrade(cfg, "head")

    # Build a sync URL for post-migration verification and role provisioning
    # testcontainers also exposes a psycopg2-compatible URL via get_connection_url(driver=None)
    sync_url = container_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    sync_engine = create_engine(sync_url, poolclass=NullPool)

    # Verify pgvector extension was created by migrations
    with sync_engine.connect() as conn:
        extversion = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
        assert extversion is not None, "pgvector extension not found after alembic upgrade head"

        # Task 2c: provision non-superuser alaya_app role
        # Check if role already exists (idempotent)
        role_exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'alaya_app'")).scalar()
        if not role_exists:
            conn.execute(text("CREATE ROLE alaya_app LOGIN PASSWORD 'test'"))
            conn.commit()

        conn.execute(text("GRANT USAGE ON SCHEMA public TO alaya_app"))
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO alaya_app"))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alaya_app"
            )
        )
        conn.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO alaya_app"))
        conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO alaya_app"))
        conn.commit()

    sync_engine.dispose()
    return pg_container


def _build_app_role_url(pg_container: PostgresContainer) -> str:
    """Build the asyncpg URL for the non-superuser alaya_app role."""
    superuser_url = pg_container.get_connection_url()
    # Extract host, port, dbname from the superuser URL
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    match = re.match(r"postgresql\+asyncpg://[^@]+@([^/]+)/(.+)", superuser_url)
    assert match, f"Could not parse container URL: {superuser_url}"
    host_port = match.group(1)
    dbname = match.group(2)
    return f"postgresql+asyncpg://alaya_app:test@{host_port}/{dbname}"


# ---------------------------------------------------------------------------
# Task 2d: engine + engine_superuser — session-scoped async fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(migrated_container: PostgresContainer):
    """Async engine for the non-superuser alaya_app role (subject to RLS)."""
    url = _build_app_role_url(migrated_container)
    eng = create_async_engine(url, echo=False, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine_superuser(migrated_container: PostgresContainer):
    """Async engine for the superuser (bypasses RLS — for seeding evidence rows)."""
    url = migrated_container.get_connection_url()
    eng = create_async_engine(url, echo=False, poolclass=NullPool)
    yield eng
    await eng.dispose()


# ---------------------------------------------------------------------------
# Task 2e: db_session — per-test async fixture using savepoint rollback
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession]:
    """Per-test async session with outer transaction + savepoint rollback.

    Each test gets a fresh savepoint. After the test the outer transaction
    is rolled back — leaving the DB clean for the next test without needing
    a truncate or DROP/CREATE cycle.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as sess:
            yield sess
        await outer.rollback()


# ---------------------------------------------------------------------------
# Workspace fixture — seeds a workspace with core entity types + predicates
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def workspace(db_session: AsyncSession):
    """A freshly seeded workspace (within the per-test savepoint transaction)."""
    ws = await workspace_service.create_workspace(
        session=db_session,
        name="Test Workspace",
        slug=f"test-ws-{uuid.uuid4().hex[:8]}",
    )
    await db_session.flush()
    # SET LOCAL at the outer connection level so all subsequent queries in
    # this test respect RLS for this workspace.
    wid = str(uuid.UUID(str(ws.id)))
    await db_session.execute(text(f"SET LOCAL app.workspace_id = '{wid}'"))
    return ws


# ---------------------------------------------------------------------------
# workspaces_a_b — yields two independently seeded workspaces
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def workspaces_a_b(db_session: AsyncSession):
    """Two seeded workspaces for cross-workspace isolation tests."""
    ws_a = await workspace_service.create_workspace(
        session=db_session,
        name="Workspace A",
        slug=f"ws-a-{uuid.uuid4().hex[:8]}",
    )
    await db_session.flush()

    ws_b = await workspace_service.create_workspace(
        session=db_session,
        name="Workspace B",
        slug=f"ws-b-{uuid.uuid4().hex[:8]}",
    )
    await db_session.flush()
    return ws_a, ws_b


# ---------------------------------------------------------------------------
# Helper: reissue_workspace_context — re-SET LOCAL after a savepoint rollback
# ---------------------------------------------------------------------------


async def reissue_workspace_context(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Re-issue SET LOCAL app.workspace_id after a nested transaction rollback.

    A rolled-back savepoint clears SET LOCAL (which is scoped to the current
    subtransaction). Call this helper to restore the workspace context before
    continuing queries in the outer transaction.
    """
    wid = str(uuid.UUID(str(workspace_id)))
    await session.execute(text(f"SET LOCAL app.workspace_id = '{wid}'"))


# ---------------------------------------------------------------------------
# session — backward-compatible fixture for test_composite_fk.py and similar tests.
# Uses the superuser engine so FK integrity tests can insert without workspace context.
# The superuser bypasses RLS, which is correct for composite FK violation tests.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(engine_superuser) -> AsyncGenerator[AsyncSession]:
    """Backward-compatible session fixture backed by the superuser engine.

    Used by test_composite_fk.py which needs to insert rows without SET LOCAL
    app.workspace_id context. Superuser bypasses RLS so FK constraint violations
    are still caught correctly. Rolls back at teardown.
    """
    session_factory = async_sessionmaker(engine_superuser, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        yield sess
        await sess.rollback()


# ---------------------------------------------------------------------------
# Legacy session_ws_a / session_ws_b fixtures — kept for test_rls.py compat
# These open their own connections using the app-role engine so RLS applies.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_ws_a(engine) -> AsyncGenerator[AsyncSession]:
    """Session with SET LOCAL for a fresh workspace A (app-role connection)."""
    ws_a_id = uuid.uuid4()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        await sess.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug) ON CONFLICT (slug) DO NOTHING"),
            {"id": ws_a_id, "name": "Workspace A", "slug": f"ws-a-{ws_a_id.hex[:8]}"},
        )
        validated_wid = str(uuid.UUID(str(ws_a_id)))
        await sess.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def session_ws_b(engine) -> AsyncGenerator[AsyncSession]:
    """Session with SET LOCAL for a fresh workspace B (app-role connection)."""
    ws_b_id = uuid.uuid4()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        await sess.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug) ON CONFLICT (slug) DO NOTHING"),
            {"id": ws_b_id, "name": "Workspace B", "slug": f"ws-b-{ws_b_id.hex[:8]}"},
        )
        validated_wid = str(uuid.UUID(str(ws_b_id)))
        await sess.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
        yield sess
        await sess.rollback()
