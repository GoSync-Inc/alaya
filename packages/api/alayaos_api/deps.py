"""Dependency injection for FastAPI routes."""

import hashlib
import hmac
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import bind_contextvars

from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.api_key import APIKeyRepository

Scope = Literal["read", "write", "admin"]

_SCOPE_TO_LEVELS: dict[Scope, set[str]] = {
    "read": {"public", "channel"},
    "write": {"public", "channel", "private"},
    "admin": {"public", "channel", "private", "restricted"},
}


def _compute_allowed_levels(scopes: list[str]) -> set[str]:
    """Return allowed access levels for scopes, failing closed to public."""
    levels: set[str] = set()
    for scope in scopes:
        if scope in _SCOPE_TO_LEVELS:
            levels.update(_SCOPE_TO_LEVELS[scope])
    return levels or {"public"}


def _error_response(code: str, message: str, hint: str | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "docs": None,
            "request_id": None,
        }
    }


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield one async session per request from the app-level session factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session, session.begin():
        yield session


async def get_api_key(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_api_key: str = Header(default=""),
) -> APIKey:
    """Verify API key from X-Api-Key header; raise 401/403 on failure."""
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail=_error_response("auth.missing_key", "API key is required."),
        )

    if not x_api_key.startswith("ak_") or len(x_api_key) < 12:
        raise HTTPException(
            status_code=401,
            detail=_error_response(
                "auth.malformed_key",
                "API key format is invalid. Must start with ak_ and be at least 12 characters.",
            ),
        )

    prefix = x_api_key[:12]
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()

    repo = APIKeyRepository(session)
    api_key = await repo.get_by_prefix(prefix)

    if api_key is None or not hmac.compare_digest(api_key.key_hash, key_hash):
        raise HTTPException(
            status_code=401,
            detail=_error_response("auth.invalid_key", "API key not found or invalid."),
        )

    from datetime import UTC, datetime

    if api_key.revoked_at is not None:
        raise HTTPException(
            status_code=401,
            detail=_error_response("auth.invalid_key", "API key has been revoked."),
        )

    if api_key.expires_at is not None and api_key.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=401,
            detail=_error_response("auth.expired_key", "API key has expired."),
        )

    return api_key


async def get_workspace_session(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
) -> AsyncGenerator[AsyncSession]:
    """Set request-scoped database context and yield the session."""
    # Re-parse to guarantee valid UUID (defense-in-depth against injection).
    validated_wid = str(uuid.UUID(str(api_key.workspace_id)))
    allowed_str = ",".join(sorted(_compute_allowed_levels(api_key.scopes)))
    await session.execute(
        text(
            "SELECT set_config('app.workspace_id', :wid, true), "
            "set_config('app.allowed_access_levels', :allowed, true), "
            "set_config('hnsw.iterative_scan', 'strict_order', true)"
        ),
        {"wid": validated_wid, "allowed": allowed_str},
    )
    bind_contextvars(workspace_id=validated_wid, allowed_access_levels=allowed_str)
    yield session


def require_scope(scope: str):
    """Return a dependency that enforces the given scope on the API key."""

    async def _check_scope(api_key: Annotated[APIKey, Depends(get_api_key)]) -> APIKey:
        has_scope = scope in api_key.scopes or (
            scope == "read" and any(s in api_key.scopes for s in ("write", "admin"))
        )
        if not has_scope:
            raise HTTPException(
                status_code=403,
                detail=_error_response(
                    "auth.insufficient_scope",
                    f"Scope '{scope}' is required for this operation.",
                ),
            )
        return api_key

    return _check_scope


def data_response(data) -> dict:
    """Single item response envelope."""
    return {"data": data}


def paginated_response(
    items,
    schema_class,
    next_cursor: str | None,
    has_more: bool,
    filtered_count: int = 0,
    filter_reason: str | None = None,
) -> dict:
    """List response with cursor pagination envelope."""
    return {
        "data": [schema_class.model_validate(item) for item in items],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "count": len(items),
        },
        "meta": {
            "filtered_count": filtered_count,
            "filter_reason": filter_reason if filtered_count > 0 else None,
        },
    }
