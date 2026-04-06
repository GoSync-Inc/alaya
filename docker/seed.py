"""Idempotent seed script — creates demo workspace, seeds types/predicates, creates bootstrap API key."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.repositories.api_key import APIKeyRepository
from alayaos_core.repositories.workspace import WorkspaceRepository
from alayaos_core.services.api_key import create_api_key
from alayaos_core.services.workspace import create_workspace, seed_core_metadata


async def seed(session: AsyncSession) -> None:
    # 1. Create demo workspace (idempotent)
    ws_repo = WorkspaceRepository(session)
    workspace = await ws_repo.get_by_slug("demo")
    if workspace is None:
        workspace = await create_workspace(session, name="Demo Workspace", slug="demo")
        await session.flush()
        print("Created demo workspace")
    else:
        # Re-run upserts for core metadata (idempotent — handles incomplete previous runs)
        await seed_core_metadata(session, workspace)
        print("Demo workspace already exists — core metadata refreshed")

    # 2. Bootstrap API key (idempotent)
    settings = Settings()
    if settings.ENV == "production":
        await session.commit()
        print("Production mode — skipping bootstrap API key")
        return

    api_key_repo = APIKeyRepository(session)
    # Check if bootstrap key exists
    keys, _, _ = await api_key_repo.list(workspace_id=workspace.id, limit=200)
    bootstrap_exists = any(k.is_bootstrap for k in keys)

    if not bootstrap_exists:
        _api_key, raw_key = await create_api_key(
            session,
            workspace_id=workspace.id,
            name="Bootstrap Key",
            scopes=["read", "write", "admin"],
            is_bootstrap=True,
        )
        await session.commit()
        print("=" * 50)
        print("Bootstrap API Key (dev only):")
        print(raw_key)
        print("=" * 50)
    else:
        await session.commit()
        print("Bootstrap API key already exists")


async def main() -> None:
    settings = Settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await seed(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
