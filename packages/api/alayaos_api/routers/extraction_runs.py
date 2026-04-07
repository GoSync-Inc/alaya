"""ExtractionRun endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.extraction_run import ExtractionRunRepository
from alayaos_core.schemas.extraction_run import ExtractionRunListRead, ExtractionRunRead

router = APIRouter()


def _not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Extraction run '{run_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/extraction-runs")
async def list_extraction_runs(
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
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

    repo = ExtractionRunRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    return paginated_response(items, ExtractionRunListRead, next_cursor, has_more)


@router.get("/extraction-runs/{run_id}")
async def get_extraction_run(
    run_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = ExtractionRunRepository(session, api_key.workspace_id)
    run = await repo.get_by_id(run_id)
    if run is None:
        raise _not_found(str(run_id))
    # Include resolver_decisions on detail view
    return data_response(ExtractionRunRead.model_validate(run))
