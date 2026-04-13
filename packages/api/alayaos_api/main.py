"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.trustedhost import TrustedHostMiddleware

from alayaos_core.config import Settings
from alayaos_core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    setup_logging(
        json_output=settings.ENV == "production",
        log_level=settings.LOG_LEVEL,
        db_echo=settings.DB_ECHO,
    )
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
    )
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = Settings()
    docs_enabled = settings.API_DOCS_ENABLED
    if docs_enabled is None:
        docs_enabled = settings.ENV != "production"

    app = FastAPI(
        title="AlayaOS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # Host validation may live here or at ingress, but production needs one of those controls.
    if settings.TRUSTED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

    from alayaos_api.middleware import register_error_handlers
    from alayaos_api.routers import (
        admin,
        api_keys,
        ask,
        chunks,
        claims,
        entities,
        entity_types,
        events,
        extraction_runs,
        health,
        ingestion,
        integrator_runs,
        pipeline_traces,
        predicates,
        relations,
        search,
        tree,
        workspaces,
    )

    register_error_handlers(app)

    app.include_router(admin.router)
    app.include_router(health.router)
    app.include_router(workspaces.router, prefix="/api/v1", tags=["workspaces"])
    app.include_router(entities.router, prefix="/api/v1", tags=["entities"])
    app.include_router(entity_types.router, prefix="/api/v1", tags=["entity-types"])
    app.include_router(events.router, prefix="/api/v1", tags=["events"])
    app.include_router(predicates.router, prefix="/api/v1", tags=["predicates"])
    app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])
    app.include_router(claims.router, prefix="/api/v1", tags=["claims"])
    app.include_router(relations.router, prefix="/api/v1", tags=["relations"])
    app.include_router(extraction_runs.router, prefix="/api/v1", tags=["extraction-runs"])
    app.include_router(ingestion.router, prefix="/api/v1", tags=["ingestion"])
    app.include_router(chunks.router, prefix="/api/v1", tags=["chunks"])
    app.include_router(pipeline_traces.router, prefix="/api/v1", tags=["pipeline-traces"])
    app.include_router(integrator_runs.router, prefix="/api/v1", tags=["integrator-runs"])
    app.include_router(tree.router, prefix="/api/v1", tags=["tree"])
    app.include_router(search.router, prefix="/api/v1", tags=["search"])
    app.include_router(ask.router, prefix="/api/v1", tags=["ask"])

    return app


app = create_app()
