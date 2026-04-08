"""Search endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_api_key, get_workspace_session
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.schemas.search import SearchRequest, SearchResponse
from alayaos_core.services.search import hybrid_search

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
):
    settings = Settings()
    embedding_service = None
    if settings.FEATURE_FLAG_VECTOR_SEARCH:
        from alayaos_core.services.embedding import FastEmbedService

        embedding_service = FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

    return await hybrid_search(
        session=session,
        query=body.query,
        workspace_id=api_key.workspace_id,
        embedding_service=embedding_service,
        limit=body.limit,
        entity_types=body.entity_types,
    )
