"""ACL-sensitive internal entity resolver paths."""

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest


@dataclass
class _Entity:
    id: uuid.UUID
    name: str
    aliases: list[str]


@pytest.mark.asyncio
async def test_resolver_llm_ambiguous_match_uses_unfiltered_internal_lookup() -> None:
    from alayaos_core.extraction.resolver import resolve_entity
    from alayaos_core.extraction.schemas import EntityMatchResult, ExtractedEntity

    existing_id = uuid.uuid4()
    existing = _Entity(id=existing_id, name="Alfa Project", aliases=[])

    class EntityRepo:
        async def get_by_external_id(self, workspace_id, source_type, ext_id):
            return None

        async def get_by_id(self, entity_id):
            raise AssertionError("filtered entity lookup used")

        async def get_by_id_unfiltered(self, entity_id):
            assert entity_id == existing_id
            return existing

    async def resolve_type(*args, **kwargs):
        raise AssertionError("resolver should merge before creating")

    llm = AsyncMock()
    llm.extract = AsyncMock(return_value=(EntityMatchResult(is_same_entity=True, reasoning="same"), None))

    entity_id, is_new, decision = await resolve_entity(
        extracted=ExtractedEntity(name="Alpha Project", entity_type="project", aliases=[], external_ids={}),
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=AsyncMock(),
        llm=llm,
        entity_index={"alfa project": existing_id},
        alias_index={},
        entity_repo=EntityRepo(),
        entity_type_resolver=resolve_type,
    )

    assert entity_id == existing_id
    assert is_new is False
    assert decision["tier"] == "llm"


@pytest.mark.asyncio
async def test_resolve_batch_builds_entity_index_with_unfiltered_internal_list() -> None:
    from alayaos_core.extraction.resolver import resolve_batch
    from alayaos_core.extraction.schemas import ExtractedEntity

    existing_id = uuid.uuid4()
    existing = _Entity(id=existing_id, name="Restricted Project", aliases=["Secret Alias"])

    class EntityRepo:
        async def list(self, *args, **kwargs):
            raise AssertionError("filtered entity list used")

        async def list_unfiltered(self, *args, **kwargs):
            assert kwargs["limit"] == 200
            return [existing], None, False

        async def get_by_external_id(self, workspace_id, source_type, ext_id):
            return None

        async def create(self, *args, **kwargs):
            raise AssertionError("resolver should reuse existing restricted entity")

    entity_name_to_id, decisions = await resolve_batch(
        extracted_entities=[
            ExtractedEntity(name="Restricted Project", entity_type="project", aliases=[], external_ids={})
        ],
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=AsyncMock(),
        llm=AsyncMock(),
        entity_repo=EntityRepo(),
    )

    assert entity_name_to_id == {"Restricted Project": existing_id}
    assert decisions[0]["tier"] == "fuzzy"
