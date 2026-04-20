"""Integration test fixtures — requires real PostgreSQL."""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alayaos_core.config import Settings
from alayaos_core.models import Base


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    settings = Settings()
    db_url = settings.DATABASE_URL.get_secret_value()
    # Safety: refuse to run against the default development database.
    if "alaya_test" not in db_url and "test" not in db_url:
        pytest.skip(
            "Integration tests require ALAYA_DATABASE_URL pointing to a test database (must contain 'test' in name)"
        )
    # NullPool: each session gets a fresh connection, no "another operation in progress"
    eng = create_async_engine(db_url, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        yield sess
        await sess.rollback()


WS_A_ID = uuid.uuid4()
WS_B_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session_ws_a(engine) -> AsyncGenerator[AsyncSession]:
    """Session with SET LOCAL for workspace A."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        await sess.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug) ON CONFLICT (slug) DO NOTHING"),
            {"id": WS_A_ID, "name": "Workspace A", "slug": "ws-a"},
        )
        validated_wid = str(uuid.UUID(str(WS_A_ID)))
        await sess.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def session_ws_b(engine) -> AsyncGenerator[AsyncSession]:
    """Session with SET LOCAL for workspace B."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess, sess.begin():
        await sess.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug) ON CONFLICT (slug) DO NOTHING"),
            {"id": WS_B_ID, "name": "Workspace B", "slug": "ws-b"},
        )
        validated_wid = str(uuid.UUID(str(WS_B_ID)))
        await sess.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
        yield sess
        await sess.rollback()
