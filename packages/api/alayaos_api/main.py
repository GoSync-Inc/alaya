"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alayaos_core.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="AlayaOS API", version="0.1.0", lifespan=lifespan)

    from alayaos_api.middleware import register_error_handlers
    from alayaos_api.routers import api_keys, entities, entity_types, events, health, predicates, workspaces

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(workspaces.router, prefix="/api/v1", tags=["workspaces"])
    app.include_router(entities.router, prefix="/api/v1", tags=["entities"])
    app.include_router(entity_types.router, prefix="/api/v1", tags=["entity-types"])
    app.include_router(events.router, prefix="/api/v1", tags=["events"])
    app.include_router(predicates.router, prefix="/api/v1", tags=["predicates"])
    app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])

    return app


app = create_app()
