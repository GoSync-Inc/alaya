"""Search/ask ACL regressions for entity description leakage."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from alayaos_core.models.claim import ClaimSource, L2Claim
from alayaos_core.models.entity import L1Entity
from alayaos_core.models.event import L0Event
from alayaos_core.services.ask import ask
from alayaos_core.services.search import hybrid_search

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _set_allowed_access(session: AsyncSession, levels: list[str]) -> None:
    await session.execute(
        text("SELECT set_config('app.allowed_access_levels', :levels, true)"),
        {"levels": ",".join(levels)},
    )


async def _create_entity_with_public_claim(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    restricted_description: str,
) -> L1Entity:
    entity_type_id = (
        await session.execute(
            text("SELECT id FROM entity_type_definitions WHERE workspace_id = :workspace_id LIMIT 1"),
            {"workspace_id": workspace_id},
        )
    ).scalar_one()
    entity = L1Entity(
        workspace_id=workspace_id,
        entity_type_id=entity_type_id,
        name=f"Visible Entity {uuid.uuid4()}",
        description=restricted_description,
        properties={"secret": restricted_description},
        is_deleted=False,
    )
    session.add(entity)
    await session.flush()
    event = L0Event(
        workspace_id=workspace_id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public evidence"},
        event_metadata={},
        access_level="public",
    )
    claim = L2Claim(
        workspace_id=workspace_id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "visible public status"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    session.add_all([event, claim])
    await session.flush()
    session.add(ClaimSource(workspace_id=workspace_id, claim_id=claim.id, event_id=event.id))
    await session.flush()
    return entity


async def test_non_admin_search_cannot_find_entity_by_restricted_description_only(
    db_session: AsyncSession,
    workspace,
) -> None:
    await _create_entity_with_public_claim(
        db_session,
        workspace.id,
        restricted_description="needleclassifiedomega",
    )
    await _set_allowed_access(db_session, ["public", "channel"])

    result = await hybrid_search(db_session, "needleclassifiedomega", workspace.id, limit=5)

    assert result.results == []


async def test_non_admin_ask_does_not_receive_restricted_description_only_evidence(
    db_session: AsyncSession,
    workspace,
) -> None:
    await _create_entity_with_public_claim(
        db_session,
        workspace.id,
        restricted_description="needleanswersecret",
    )
    await _set_allowed_access(db_session, ["public", "channel"])
    llm = AsyncMock()

    result = await ask(
        session=db_session,
        question="needleanswersecret",
        workspace_id=workspace.id,
        llm=llm,
    )

    assert result.answerable is False
    assert result.evidence == []
    llm.extract.assert_not_awaited()
