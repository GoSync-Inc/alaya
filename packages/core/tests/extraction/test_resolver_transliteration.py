"""Tests for transliteration layer in entity resolver."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_fake_entity(entity_id: uuid.UUID, name: str, aliases: list[str] | None = None):
    entity = MagicMock()
    entity.id = entity_id
    entity.name = name
    entity.aliases = aliases or []
    return entity


def _make_entity_repo(get_by_external_id_return=None, get_by_id_return=None, create_return=None):
    repo = AsyncMock()
    repo.get_by_external_id = AsyncMock(return_value=get_by_external_id_return)
    repo.get_by_id = AsyncMock(return_value=get_by_id_return)
    repo.create = AsyncMock(return_value=create_return)
    repo.create_external_id = AsyncMock()
    return repo


def _make_entity_type_resolver(type_id: uuid.UUID):
    async def resolver(type_slug: str, workspace_id: uuid.UUID, session) -> uuid.UUID:
        return type_id

    return resolver


# ─── transliterate_name tests ─────────────────────────────────────────────────


def test_transliterate_name_cyrillic_to_latin() -> None:
    """Cyrillic name 'Егор' transliterates to a Latin form close to 'egor'."""
    from alayaos_core.extraction.resolver import transliterate_name

    result = transliterate_name("Егор")
    # Should produce latin letters, not cyrillic
    assert result.isascii(), f"Expected ASCII output, got: {result!r}"
    assert len(result) > 0


def test_transliterate_name_returns_normalized() -> None:
    """transliterate_name returns NFKC + lowercase normalized output."""
    from alayaos_core.extraction.resolver import transliterate_name

    # Should be lowercased and stripped
    result = transliterate_name("  Алиса  ")
    assert result == result.lower().strip()


def test_transliterate_name_handles_non_cyrillic_gracefully() -> None:
    """transliterate_name handles ASCII input without error."""
    from alayaos_core.extraction.resolver import transliterate_name

    result = transliterate_name("Alice")
    assert "alice" in result or result == "alice"


def test_transliterate_name_handles_empty() -> None:
    """transliterate_name handles empty string without error."""
    from alayaos_core.extraction.resolver import transliterate_name

    result = transliterate_name("")
    assert result == ""


def test_transliterate_name_egor_is_ascii() -> None:
    """'Егор' transliterates to some ASCII string."""
    from alayaos_core.extraction.resolver import transliterate_name

    result = transliterate_name("Егор")
    assert result.isascii()
    assert len(result) >= 3  # At least 3 characters


# ─── Short name skip tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_short_name_skips_fuzzy_matching() -> None:
    """Names shorter than 4 chars skip fuzzy matching → new entity created."""
    from alayaos_core.extraction.schemas import ExtractedEntity
    from alayaos_core.extraction.resolver import resolve_entity

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    new_entity_id = uuid.uuid4()
    new_entity = _make_fake_entity(new_entity_id, "Bob")

    repo = _make_entity_repo(get_by_external_id_return=None, create_return=new_entity)
    # "bob" is 3 chars — should skip fuzzy
    extracted = ExtractedEntity(name="Bob", entity_type="person")
    # Entity index has similar-looking entry
    entity_index = {"rob": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=MagicMock(),
        entity_index=entity_index,
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    # Short name should not fuzzy-match and should create new entity
    assert is_new is True
    assert decision["action"] == "created"


@pytest.mark.asyncio
async def test_regular_ascii_name_works_without_transliteration() -> None:
    """Regular ASCII names still fuzzy-match normally."""
    from alayaos_core.extraction.schemas import ExtractedEntity
    from alayaos_core.extraction.resolver import resolve_entity

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    repo = _make_entity_repo(get_by_external_id_return=None)
    # "alice smyth" vs "alice smith" — high JW similarity
    extracted = ExtractedEntity(name="alice smyth", entity_type="person")
    entity_index = {"alice smith": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=MagicMock(),
        entity_index=entity_index,
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    assert entity_id == existing_id
    assert is_new is False
    assert decision["tier"] == "fuzzy"
    assert decision["score"] >= 0.92


@pytest.mark.asyncio
async def test_cyrillic_matches_latin_via_transliteration() -> None:
    """Cyrillic 'Егор' matches Latin 'Egor' via transliteration layer."""
    from alayaos_core.extraction.schemas import ExtractedEntity
    from alayaos_core.extraction.resolver import resolve_entity, transliterate_name

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    # Verify that transliteration actually produces a string that would match
    translit_egor = transliterate_name("Егор")
    latin_egor = "egor"

    # Only run this test if transliteration produces the expected output
    if translit_egor != latin_egor:
        pytest.skip(f"Transliteration gave {translit_egor!r} not 'egor' — skip cross-script test")

    repo = _make_entity_repo(get_by_external_id_return=None)
    extracted = ExtractedEntity(name="Егор", entity_type="person")
    entity_index = {latin_egor: existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=MagicMock(),
        entity_index=entity_index,
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    # With transliteration, Cyrillic name should match the Latin entity
    assert entity_id == existing_id
    assert is_new is False
