"""Q&A service: search → LLM → validated citations."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

from alayaos_core.config import Settings
from alayaos_core.schemas.search import EvidenceUnit  # noqa: TC001
from alayaos_core.services.search import hybrid_search

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.llm.interface import LLMServiceInterface
    from alayaos_core.services.embedding import EmbeddingServiceInterface

log = structlog.get_logger()


class AskCitation(BaseModel):
    claim_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    snippet: str


class AskResponseModel(BaseModel):
    """Pydantic model for LLM structured output."""

    answer: str
    answerable: bool
    citations: list[AskCitation]


class AskResult(BaseModel):
    answer: str
    answerable: bool
    citations: list[AskCitation]
    evidence: list[EvidenceUnit]
    tokens_used: int
    cost_usd: float


async def ask(
    session: AsyncSession,
    question: str,
    workspace_id: uuid.UUID,
    llm: LLMServiceInterface,
    *,
    embedding_service: EmbeddingServiceInterface | None = None,
    max_results: int = 10,
) -> AskResult:
    settings = Settings()

    search_response = await hybrid_search(
        session=session,
        query=question,
        workspace_id=workspace_id,
        embedding_service=embedding_service,
        limit=max_results,
    )

    evidence = search_response.results

    if not evidence:
        return AskResult(
            answer="I don't have enough information to answer this question.",
            answerable=False,
            citations=[],
            evidence=[],
            tokens_used=0,
            cost_usd=0.0,
        )

    context_parts = []
    for unit in evidence[: settings.ASK_MAX_RESULTS_FOR_LLM]:
        context_parts.append(f"[{unit.source_type}:{unit.source_id}] {unit.content}")
    context_text = _sanitize_context("\n".join(context_parts))

    system_prompt = (
        "You are a corporate knowledge assistant. "
        "Answer the question using ONLY the information in <context>. "
        "If the context doesn't contain enough information, set answerable=false. "
        "Cite specific evidence using claim_id or entity_id from the context."
    )
    text = f"<context>\n{context_text}\n</context>\n\n<question>\n{question}\n</question>"

    response, usage = await llm.extract(
        text=text,
        system_prompt=system_prompt,
        response_model=AskResponseModel,
        max_tokens=settings.ASK_MAX_OUTPUT_TOKENS,
    )

    # Collect valid IDs from all evidence (including chunk-sourced with entity_id/claim_id)
    valid_entity_ids = {u.source_id for u in evidence if u.source_type == "entity"}
    valid_entity_ids |= {u.entity_id for u in evidence if u.entity_id is not None}
    valid_claim_ids = {u.source_id for u in evidence if u.source_type == "claim"}
    valid_claim_ids |= {u.claim_id for u in evidence if u.claim_id is not None}
    validated_citations = []
    for c in response.citations:
        if c.entity_id and c.entity_id not in valid_entity_ids:
            continue
        if c.claim_id and c.claim_id not in valid_claim_ids:
            continue
        validated_citations.append(c)

    return AskResult(
        answer=response.answer,
        answerable=response.answerable,
        citations=validated_citations,
        evidence=evidence,
        tokens_used=usage.tokens_in + usage.tokens_out,
        cost_usd=usage.cost_usd,
    )


def _sanitize_context(text: str) -> str:
    """Strip instruction-like patterns from evidence content."""
    patterns = [
        r"<system>.*?</system>",
        r"<assistant>.*?</assistant>",
        r"(?i)ignore\s+(all\s+)?(previous|above|all)\s+instructions?",
        r"(?i)you\s+are\s+(now|a)\s+",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text, flags=re.DOTALL)
    return text
