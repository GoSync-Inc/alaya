"""Workspace CRUD endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.workspace import WorkspaceRepository
from alayaos_core.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from alayaos_core.services.workspace import create_workspace

router = APIRouter()


def _not_found(resource_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Workspace '{resource_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.post("/workspaces", status_code=201)
async def create_workspace_endpoint(
    body: WorkspaceCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    """Create a new workspace. Only bootstrap or admin-scoped keys allowed."""
    if not api_key.is_bootstrap:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "auth.insufficient_scope",
                    "message": "Only bootstrap keys can create workspaces.",
                    "hint": None,
                    "docs": None,
                    "request_id": None,
                }
            },
        )
    try:
        workspace = await create_workspace(session, name=body.name, slug=body.slug)
    except IntegrityError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "resource.already_exists",
                    "message": f"Workspace with slug '{body.slug}' already exists.",
                    "hint": None,
                    "docs": None,
                    "request_id": None,
                }
            },
        ) from e
    return data_response(WorkspaceRead.model_validate(workspace))


@router.get("/workspaces")
async def list_workspaces(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
    cursor: str | None = None,
    limit: int = 50,
):
    if cursor is not None:
        try:
            BaseRepository.decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "validation.invalid_cursor",
                        "message": "Invalid pagination cursor.",
                        "hint": None,
                        "docs": None,
                        "request_id": None,
                    }
                },
            ) from e

    repo = WorkspaceRepository(session)

    if api_key.is_bootstrap:
        # Bootstrap key can see all workspaces
        items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    else:
        # Regular key can only see its own workspace
        workspace = await repo.get_by_id(api_key.workspace_id)
        items = [workspace] if workspace else []
        next_cursor = None
        has_more = False

    return paginated_response(items, WorkspaceRead, next_cursor, has_more)


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    if not api_key.is_bootstrap and api_key.workspace_id != workspace_id:
        raise _not_found(str(workspace_id))

    repo = WorkspaceRepository(session)
    workspace = await repo.get_by_id(workspace_id)
    if workspace is None:
        raise _not_found(str(workspace_id))
    return data_response(WorkspaceRead.model_validate(workspace))


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    if not api_key.is_bootstrap and api_key.workspace_id != workspace_id:
        raise _not_found(str(workspace_id))

    repo = WorkspaceRepository(session)
    updates = body.model_dump(exclude_none=True)
    workspace = await repo.update(workspace_id, **updates)
    if workspace is None:
        raise _not_found(str(workspace_id))
    return data_response(WorkspaceRead.model_validate(workspace))
