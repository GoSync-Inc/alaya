"""IntegratorRun endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import (
    data_response,
    get_workspace_session,
    paginated_response,
    require_scope,
)
from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository
from alayaos_core.repositories.integrator_run import IntegratorRunRepository
from alayaos_core.schemas.integrator_run import IntegratorRunRead

router = APIRouter()


def _not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "resource.not_found",
                "message": f"Integrator run '{run_id}' not found.",
                "hint": None,
                "docs": None,
                "request_id": None,
            }
        },
    )


@router.get("/integrator-runs")
async def list_integrator_runs(
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

    repo = IntegratorRunRepository(session, api_key.workspace_id)
    items, next_cursor, has_more = await repo.list(cursor=cursor, limit=limit)
    return paginated_response(items, IntegratorRunRead, next_cursor, has_more)


@router.get("/integrator-runs/{run_id}")
async def get_integrator_run(
    run_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(require_scope("read"))],
):
    repo = IntegratorRunRepository(session, api_key.workspace_id)
    run = await repo.get_by_id(run_id)
    if run is None:
        raise _not_found(str(run_id))
    return data_response(IntegratorRunRead.model_validate(run))


@router.post("/integrator-runs/trigger", status_code=202)
async def trigger_integrator_run(
    request: Request,
    api_key: Annotated[APIKey, Depends(require_scope("admin"))],
):
    """Manually trigger an integrator run for the current workspace."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session, session.begin():
        validated_wid = str(uuid.UUID(str(api_key.workspace_id)))
        await session.execute(text(f"SET LOCAL app.workspace_id = '{validated_wid}'"))
        repo = IntegratorRunRepository(session, api_key.workspace_id)
        run = await repo.create(
            workspace_id=api_key.workspace_id,
            trigger="manual",
            scope_description="manual trigger via API",
        )

    # Enqueue the job (non-blocking; worker may not be running)
    try:
        from alayaos_core.worker.tasks import job_integrate

        await job_integrate.kiq(str(api_key.workspace_id), str(run.id))
    except Exception:
        pass

    return data_response(IntegratorRunRead.model_validate(run))
