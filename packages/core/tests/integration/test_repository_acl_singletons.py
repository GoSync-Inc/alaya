"""Repository singleton ACL filters."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.chunk import L0Chunk
from alayaos_core.models.claim import ClaimSource, L2Claim
from alayaos_core.models.entity import L1Entity
from alayaos_core.models.event import L0Event
from alayaos_core.models.relation import L1Relation, RelationSource
from alayaos_core.repositories.chunk import ChunkRepository
from alayaos_core.repositories.claim import ClaimRepository
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.event import EventRepository
from alayaos_core.repositories.relation import RelationRepository

pytestmark = pytest.mark.integration


async def _set_allowed_access(session: AsyncSession, levels: list[str]) -> None:
    await session.execute(
        text("SELECT set_config('app.allowed_access_levels', :levels, true)"),
        {"levels": ",".join(levels)},
    )


async def _create_entity(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    description: str | None = None,
    properties: dict | None = None,
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
        name=f"Entity {uuid.uuid4()}",
        description=description,
        properties=properties or {},
        is_deleted=False,
    )
    session.add(entity)
    await session.flush()
    return entity


async def test_event_get_by_id_hides_disallowed_access_level(
    db_session: AsyncSession,
    workspace,
) -> None:
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"msg-{uuid.uuid4()}",
        content={"text": "restricted launch plan"},
        event_metadata={},
        access_level="restricted",
    )
    db_session.add(event)
    await db_session.flush()
    await _set_allowed_access(db_session, ["public", "channel"])

    repo = EventRepository(db_session, workspace.id)

    assert await repo.get_by_id(event.id) is None


async def test_event_list_hides_disallowed_access_level_and_counts_filtered_rows(
    db_session: AsyncSession,
    workspace,
) -> None:
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public update"},
        event_metadata={},
        access_level="public",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted update"},
        event_metadata={},
        access_level="restricted",
    )
    db_session.add_all([public_event, restricted_event])
    await db_session.flush()
    await _set_allowed_access(db_session, ["public"])

    repo = EventRepository(db_session, workspace.id)
    items, _cursor, has_more = await repo.list()

    assert [item.id for item in items] == [public_event.id]
    assert has_more is False
    assert repo.last_filtered_count == 1


async def test_claim_get_by_id_treats_source_less_claims_as_admin_only(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "stealth"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add(claim)
    await db_session.flush()

    repo = ClaimRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public", "channel", "private"])
    assert await repo.get_by_id(claim.id) is None

    await _set_allowed_access(db_session, ["public", "channel", "private", "restricted"])
    assert await repo.get_by_id(claim.id) is claim


async def test_claim_create_returns_inserted_claim_before_source_link_exists(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    repo = ClaimRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public"])

    claim = await repo.create(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "new"},
    )

    assert claim.id is not None


async def test_claim_internal_status_and_supersession_bypass_acl_without_allowed_access_guc(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted evidence"},
        event_metadata={},
        access_level="restricted",
    )
    old_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "old"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    new_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "new"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([event, old_claim, new_claim])
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=old_claim.id, event_id=event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=new_claim.id, event_id=event.id),
        ]
    )
    await db_session.flush()
    await db_session.execute(text("RESET app.allowed_access_levels"))

    repo = ClaimRepository(db_session, workspace.id)
    assert await repo.get_by_id(old_claim.id) is None
    assert await repo.get_by_id(new_claim.id) is None

    assert await repo.update_status_unfiltered(new_claim.id, "disputed") is new_claim
    assert await repo.mark_superseded_unfiltered(old_claim.id, new_claim.id, event.occurred_at) is old_claim

    assert old_claim.status == "superseded"
    assert old_claim.valid_to == event.occurred_at
    assert new_claim.status == "disputed"
    assert new_claim.supersedes == old_claim.id


async def test_claim_list_hides_disallowed_claims_and_counts_filtered_rows(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public evidence"},
        event_metadata={},
        access_level="public",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted evidence"},
        event_metadata={},
        access_level="restricted",
    )
    public_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "public"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    restricted_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "restricted"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([public_event, restricted_event, public_claim, restricted_claim])
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=public_claim.id, event_id=public_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=restricted_claim.id, event_id=restricted_event.id),
        ]
    )
    await db_session.flush()
    await _set_allowed_access(db_session, ["public"])

    repo = ClaimRepository(db_session, workspace.id)
    items, _cursor, has_more = await repo.list(status="active")

    assert [item.id for item in items] == [public_claim.id]
    assert has_more is False
    assert repo.last_filtered_count == 1


async def test_claim_list_unfiltered_includes_private_and_restricted_claims_for_internal_context(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public evidence"},
        event_metadata={},
        access_level="public",
    )
    private_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"private-{uuid.uuid4()}",
        content={"text": "private evidence"},
        event_metadata={},
        access_level="private",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted evidence"},
        event_metadata={},
        access_level="restricted",
    )
    public_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "public"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    private_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "private"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    restricted_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "restricted"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([public_event, private_event, restricted_event, public_claim, private_claim, restricted_claim])
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=public_claim.id, event_id=public_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=private_claim.id, event_id=private_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=restricted_claim.id, event_id=restricted_event.id),
        ]
    )
    await db_session.flush()
    await _set_allowed_access(db_session, ["public"])

    repo = ClaimRepository(db_session, workspace.id)
    public_items, _cursor, _has_more = await repo.list(entity_id=entity.id, status="active")
    internal_items, _cursor, _has_more = await repo.list_unfiltered(entity_id=entity.id, status="active")

    assert [item.id for item in public_items] == [public_claim.id]
    assert {item.id for item in internal_items} == {public_claim.id, private_claim.id, restricted_claim.id}


async def test_chunk_get_and_list_hide_chunks_for_disallowed_events(
    db_session: AsyncSession,
    workspace,
) -> None:
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public event"},
        event_metadata={},
        access_level="public",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted event"},
        event_metadata={},
        access_level="restricted",
    )
    db_session.add_all([public_event, restricted_event])
    await db_session.flush()
    public_chunk = L0Chunk(
        workspace_id=workspace.id,
        event_id=public_event.id,
        chunk_index=0,
        chunk_total=1,
        text="public chunk text",
        token_count=3,
        source_type="slack",
    )
    restricted_chunk = L0Chunk(
        workspace_id=workspace.id,
        event_id=restricted_event.id,
        chunk_index=0,
        chunk_total=1,
        text="restricted chunk text",
        token_count=3,
        source_type="slack",
    )
    db_session.add_all([public_chunk, restricted_chunk])
    await db_session.flush()
    await _set_allowed_access(db_session, ["public", "channel"])

    repo = ChunkRepository(db_session, workspace.id)

    assert await repo.get_by_id(restricted_chunk.id) is None
    items, _cursor, has_more = await repo.list()
    assert [item.id for item in items] == [public_chunk.id]
    assert has_more is False
    assert repo.last_filtered_count == 1


async def test_relation_get_and_list_hide_relations_with_only_disallowed_sources(
    db_session: AsyncSession,
    workspace,
) -> None:
    source_entity = await _create_entity(db_session, workspace.id)
    target_entity = await _create_entity(db_session, workspace.id)
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public relation evidence"},
        event_metadata={},
        access_level="public",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted relation evidence"},
        event_metadata={},
        access_level="restricted",
    )
    source_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=source_entity.id,
        predicate="status",
        value={"v": "visible source"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    target_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=target_entity.id,
        predicate="status",
        value={"v": "visible target"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    public_relation = L1Relation(
        workspace_id=workspace.id,
        source_entity_id=source_entity.id,
        target_entity_id=target_entity.id,
        relation_type="member_of",
        confidence=0.9,
    )
    restricted_relation = L1Relation(
        workspace_id=workspace.id,
        source_entity_id=target_entity.id,
        target_entity_id=source_entity.id,
        relation_type="reports_to",
        confidence=0.9,
    )
    db_session.add_all(
        [
            public_event,
            restricted_event,
            source_claim,
            target_claim,
            public_relation,
            restricted_relation,
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=source_claim.id, event_id=public_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=target_claim.id, event_id=public_event.id),
            RelationSource(workspace_id=workspace.id, relation_id=public_relation.id, event_id=public_event.id),
            RelationSource(workspace_id=workspace.id, relation_id=restricted_relation.id, event_id=restricted_event.id),
        ]
    )
    await db_session.flush()
    await _set_allowed_access(db_session, ["public", "channel"])

    repo = RelationRepository(db_session, workspace.id)

    assert await repo.get_by_id(restricted_relation.id) is None
    items, _cursor, has_more = await repo.list()
    assert [item.id for item in items] == [public_relation.id]
    assert has_more is False
    assert repo.last_filtered_count == 1

    await _set_allowed_access(db_session, ["public", "channel", "private", "restricted"])
    assert await repo.get_by_id(restricted_relation.id) is restricted_relation
    admin_items, _cursor, has_more = await repo.list()
    assert {item.id for item in admin_items} == {public_relation.id, restricted_relation.id}
    assert has_more is False


async def test_relation_get_and_list_treat_sourceless_relations_as_restricted(
    db_session: AsyncSession,
    workspace,
) -> None:
    source_entity = await _create_entity(db_session, workspace.id)
    target_entity = await _create_entity(db_session, workspace.id)
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public endpoint evidence"},
        event_metadata={},
        access_level="public",
    )
    source_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=source_entity.id,
        predicate="status",
        value={"v": "visible source"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    target_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=target_entity.id,
        predicate="status",
        value={"v": "visible target"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    sourceless_relation = L1Relation(
        workspace_id=workspace.id,
        source_entity_id=source_entity.id,
        target_entity_id=target_entity.id,
        relation_type="member_of",
        confidence=0.9,
    )
    db_session.add_all([public_event, source_claim, target_claim, sourceless_relation])
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=source_claim.id, event_id=public_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=target_claim.id, event_id=public_event.id),
        ]
    )
    await db_session.flush()

    repo = RelationRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public"])
    assert await repo.get_by_id(sourceless_relation.id) is None
    public_items, _cursor, _has_more = await repo.list()
    assert sourceless_relation.id not in [item.id for item in public_items]

    await _set_allowed_access(db_session, ["public", "channel", "private", "restricted"])
    assert await repo.get_by_id(sourceless_relation.id) is sourceless_relation
    admin_items, _cursor, _has_more = await repo.list()
    assert sourceless_relation.id in [item.id for item in admin_items]


async def test_relation_create_writes_source_event_provenance(
    db_session: AsyncSession,
    workspace,
) -> None:
    source_entity = await _create_entity(db_session, workspace.id)
    target_entity = await _create_entity(db_session, workspace.id)
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted relation evidence"},
        event_metadata={},
        access_level="restricted",
    )
    db_session.add(event)
    await db_session.flush()

    repo = RelationRepository(db_session, workspace.id)
    relation = await repo.create(
        workspace_id=workspace.id,
        source_entity_id=source_entity.id,
        target_entity_id=target_entity.id,
        relation_type="member_of",
        source_event_id=event.id,
    )

    row = (
        (
            await db_session.execute(
                text(
                    """
                SELECT workspace_id, relation_id, event_id
                FROM relation_sources
                WHERE workspace_id = :workspace_id AND relation_id = :relation_id
                """
                ),
                {"workspace_id": workspace.id, "relation_id": relation.id},
            )
        )
        .mappings()
        .one()
    )
    assert row["workspace_id"] == workspace.id
    assert row["relation_id"] == relation.id
    assert row["event_id"] == event.id


async def test_entity_get_by_id_requires_visible_active_claim(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"msg-{uuid.uuid4()}",
        content={"text": "restricted entity evidence"},
        event_metadata={},
        access_level="restricted",
    )
    claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "restricted"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([event, claim])
    await db_session.flush()
    db_session.add(ClaimSource(workspace_id=workspace.id, claim_id=claim.id, event_id=event.id))
    await db_session.flush()

    repo = EntityRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public", "channel", "private"])
    assert await repo.get_by_id(entity.id) is None

    await _set_allowed_access(db_session, ["public", "channel", "private", "restricted"])
    assert await repo.get_by_id(entity.id) is entity


async def test_entity_list_hides_entities_without_visible_active_claim_and_counts_filtered_rows(
    db_session: AsyncSession,
    workspace,
) -> None:
    public_entity = await _create_entity(db_session, workspace.id)
    restricted_entity = await _create_entity(db_session, workspace.id)
    public_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public entity evidence"},
        event_metadata={},
        access_level="public",
    )
    restricted_event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"restricted-{uuid.uuid4()}",
        content={"text": "restricted entity evidence"},
        event_metadata={},
        access_level="restricted",
    )
    public_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=public_entity.id,
        predicate="status",
        value={"v": "public"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    restricted_claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=restricted_entity.id,
        predicate="status",
        value={"v": "restricted"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([public_event, restricted_event, public_claim, restricted_claim])
    await db_session.flush()
    db_session.add_all(
        [
            ClaimSource(workspace_id=workspace.id, claim_id=public_claim.id, event_id=public_event.id),
            ClaimSource(workspace_id=workspace.id, claim_id=restricted_claim.id, event_id=restricted_event.id),
        ]
    )
    await db_session.flush()
    await _set_allowed_access(db_session, ["public"])

    repo = EntityRepository(db_session, workspace.id)
    items, _cursor, has_more = await repo.list()

    assert [item.id for item in items] == [public_entity.id]
    assert has_more is False
    assert repo.last_filtered_count == 1


async def test_entity_get_by_id_masks_description_and_properties_for_non_admin_visible_claim(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(
        db_session,
        workspace.id,
        description="restricted acquisition codename",
        properties={"secret": "board-only"},
    )
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public entity evidence"},
        event_metadata={},
        access_level="public",
    )
    claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "public"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([event, claim])
    await db_session.flush()
    db_session.add(ClaimSource(workspace_id=workspace.id, claim_id=claim.id, event_id=event.id))
    await db_session.flush()
    await _set_allowed_access(db_session, ["public", "channel"])

    visible_entity = await EntityRepository(db_session, workspace.id).get_by_id(entity.id)

    assert visible_entity is not None
    assert visible_entity.id == entity.id
    assert visible_entity.name == entity.name
    assert visible_entity.description is None
    assert visible_entity.properties == {}


async def test_entity_list_masks_description_and_properties_for_non_admin_visible_claim(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(
        db_session,
        workspace.id,
        description="restricted roadmap narrative",
        properties={"secret": "launch-window"},
    )
    event = L0Event(
        workspace_id=workspace.id,
        source_type="slack",
        source_id=f"public-{uuid.uuid4()}",
        content={"text": "public entity evidence"},
        event_metadata={},
        access_level="public",
    )
    claim = L2Claim(
        workspace_id=workspace.id,
        entity_id=entity.id,
        predicate="status",
        value={"v": "public"},
        confidence=0.9,
        status="active",
        value_type="text",
    )
    db_session.add_all([event, claim])
    await db_session.flush()
    db_session.add(ClaimSource(workspace_id=workspace.id, claim_id=claim.id, event_id=event.id))
    await db_session.flush()
    await _set_allowed_access(db_session, ["public", "channel"])

    items, _cursor, has_more = await EntityRepository(db_session, workspace.id).list()

    assert has_more is False
    assert len(items) == 1
    assert items[0].id == entity.id
    assert items[0].description is None
    assert items[0].properties == {}


async def test_entity_create_returns_inserted_entity_before_claim_exists(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity_type_id = (
        await db_session.execute(
            text("SELECT id FROM entity_type_definitions WHERE workspace_id = :workspace_id LIMIT 1"),
            {"workspace_id": workspace.id},
        )
    ).scalar_one()
    repo = EntityRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public"])

    entity = await repo.create(
        workspace_id=workspace.id,
        entity_type_id=entity_type_id,
        name="Claimless Entity",
    )

    assert entity.id is not None
    assert entity.external_ids == []


async def test_entity_get_by_id_unfiltered_allows_internal_claimless_lookup(
    db_session: AsyncSession,
    workspace,
) -> None:
    entity = await _create_entity(db_session, workspace.id)
    repo = EntityRepository(db_session, workspace.id)
    await _set_allowed_access(db_session, ["public"])

    assert await repo.get_by_id(entity.id) is None
    assert await repo.get_by_id_unfiltered(entity.id) is entity
