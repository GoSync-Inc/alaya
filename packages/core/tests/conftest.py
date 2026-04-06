"""Integration test fixtures — requires real PostgreSQL."""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    settings = Settings()
    eng = create_async_engine(settings.DATABASE_URL, echo=False)
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
        # Create workspace A if needed
        await sess.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug) ON CONFLICT (slug) DO NOTHING"),
            {"id": WS_A_ID, "name": "Workspace A", "slug": "ws-a"},
        )
        await sess.execute(text("SET LOCAL app.workspace_id = :wid"), {"wid": str(WS_A_ID)})
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
        await sess.execute(text("SET LOCAL app.workspace_id = :wid"), {"wid": str(WS_B_ID)})
        yield sess
        await sess.rollback()
