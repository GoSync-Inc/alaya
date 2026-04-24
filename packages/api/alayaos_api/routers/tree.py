"""Knowledge tree endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from alayaos_api.deps import (
    _compute_allowed_levels,
    data_response,
    get_workspace_session,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.schemas.tree import TreeExportRequest
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


def _allowed_tiers_from_context(api_key: APIKey) -> set[str]:
    allowed = get_contextvars().get("allowed_access_levels")
    if isinstance(allowed, str) and allowed:
        return {tier for tier in allowed.split(",") if tier}
    if isinstance(allowed, (list, set, tuple)):
        return {str(tier) for tier in allowed}
    return _compute_allowed_levels(api_key.scopes)


def _tree_node_payload(node, allowed_tiers: set[str], *, hide_non_admin_markdown: bool = False) -> dict:
    is_admin_view = "restricted" in allowed_tiers
    hide_markdown = not is_admin_view and (hide_non_admin_markdown or node.entity_id is None)
    return {
        "id": node.id,
        "path": node.path,
        "workspace_id": node.workspace_id,
        "entity_id": node.entity_id,
        "node_type": node.node_type,
        "is_dirty": node.is_dirty,
        "last_rebuilt_at": node.last_rebuilt_at,
        "markdown_cache": None if hide_markdown else node.markdown_cache,
        "summary": node.summary if is_admin_view else None,
    }


@router.get("/tree")
async def get_tree_root(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    """Return root-level tree index nodes."""
    svc = TreeService(session, api_key.workspace_id)
    allowed_tiers = _allowed_tiers_from_context(api_key)
    nodes = await svc.get_root()
    return {"data": [_tree_node_payload(n, allowed_tiers, hide_non_admin_markdown=True) for n in nodes]}


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
    allowed_tiers = _allowed_tiers_from_context(api_key)
    node = await svc.get_node(path, allowed_tiers=allowed_tiers)
    if node is None:
        raise _not_found(path)
    return data_response(_tree_node_payload(node, allowed_tiers))


@router.post("/tree/export")
async def export_subtree(
    body: TreeExportRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    """Export a subtree as markdown text."""
    svc = TreeService(session, api_key.workspace_id)
    allowed_tiers = _allowed_tiers_from_context(api_key)
    markdown = await svc.export_subtree(body.path, allowed_tiers=allowed_tiers)
    return PlainTextResponse(content=markdown, media_type="text/markdown")
