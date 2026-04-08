"""Ask (Q&A) endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_api.deps import get_api_key, get_workspace_session
from alayaos_core.config import Settings
from alayaos_core.models.api_key import APIKey
from alayaos_core.services.ask import AskResult, ask

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=20)


@router.post("/ask", response_model=AskResult)
async def ask_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
):
    settings = Settings()

    if settings.ANTHROPIC_API_KEY.get_secret_value():
        from alayaos_core.llm.anthropic import AnthropicAdapter

        llm = AnthropicAdapter(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.ASK_MODEL)
    else:
        from alayaos_core.llm.fake import FakeLLMAdapter

        llm = FakeLLMAdapter()

    embedding_service = None
    if settings.FEATURE_FLAG_VECTOR_SEARCH:
        from alayaos_core.services.embedding import FastEmbedService

        embedding_service = FastEmbedService(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

    return await ask(
        session=session,
        question=body.question,
        workspace_id=api_key.workspace_id,
        llm=llm,
        embedding_service=embedding_service,
        max_results=body.max_results,
    )
