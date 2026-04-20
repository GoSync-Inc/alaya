"""FastAPI application factory."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alayaos_core.config import Settings
from alayaos_core.logging import setup_logging

log = structlog.get_logger()


_DEFAULT_SECRET_KEY = "change-me-in-production"


def _validate_production_secrets(settings: Settings) -> None:
    """Fail-fast if production is running with insecure defaults."""
    if settings.ENV != "production":
        return
    if settings.SECRET_KEY.get_secret_value() == _DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "ALAYA_SECRET_KEY must be set to a non-default value in production. "
            "Generate a strong random value and set ALAYA_SECRET_KEY env var."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    # Redundant guard — create_app() also validates at import time so
    # the check stays effective even when lifespan is skipped
    # (e.g. `uvicorn --lifespan off` or ASGI wrappers).
    _validate_production_secrets(settings)
    setup_logging(
        json_output=settings.ENV == "production",
        log_level=settings.LOG_LEVEL,
        db_echo=settings.DB_ECHO,
    )
    engine = create_async_engine(
        settings.DATABASE_URL.get_secret_value(),
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
    # Fail fast at import time — some deployment paths skip lifespan
    # (uvicorn --lifespan off, test fixtures, ASGI wrappers), so the
    # production-secret validation must run here too.
    _validate_production_secrets(settings)
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
        from alayaos_api.middleware import EnvelopeTrustedHostMiddleware

        app.add_middleware(EnvelopeTrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)
    elif settings.ENV == "production":
        log.warning(
            "trusted_hosts_not_configured_for_production",
            message="Host validation is not configured for production. Set ALAYA_TRUSTED_HOSTS or enforce trusted hosts at ingress.",
        )

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
