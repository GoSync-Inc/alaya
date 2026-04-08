"""Knowledge tree endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.schemas.tree import TreeExportRequest, TreeNodeResponse
from alayaos_core.services.tree import TreeService

router = APIRouter()


def _not_found(path: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Tree node '{path}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/tree")
async def get_tree_root(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    """Return root-level tree index nodes."""
    svc = TreeService(session, api_key.workspace_id)
    nodes = await svc.get_root()
    return {"data": [TreeNodeResponse.model_validate(n) for n in nodes]}


@router.get("/tree/{path:path}")
async def get_tree_node(
    path: str,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    """Return a single tree node at the given path."""
    # Basic path validation
    if ".." in path or "//" in path or "\x00" in path:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "validation.invalid_path",
                    "message": "Invalid path.",
                    "hint": "Path must not contain '..', '//', or null bytes.",
                    "docs": None,
                    "request_id": None,
                }
            },
        )
    svc = TreeService(session, api_key.workspace_id)
    node = await svc.get_node(path)
    if node is None:
        raise _not_found(path)
    return data_response(TreeNodeResponse.model_validate(node))


@router.post("/tree/export")
async def export_subtree(
    body: TreeExportRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    """Export a subtree as markdown text."""
    svc = TreeService(session, api_key.workspace_id)
    markdown = await svc.export_subtree(body.path)
    return PlainTextResponse(content=markdown, media_type="text/markdown")
