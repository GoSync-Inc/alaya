"""Tests for entity resolution logic (resolver.py)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.resolver import normalize_name, resolve_entity, resolve_entity_type_id
from alayaos_core.extraction.schemas import EntityMatchResult, ExtractedEntity
from alayaos_core.llm.fake import FakeLLMAdapter

# ─── Task 1: Name Normalization ───────────────────────────────────────────────


def test_normalize_name_nfkc() -> None:
    """Fullwidth chars should be normalized to ASCII equivalents."""
    assert normalize_name("\uff28ello") == "hello"  # fullwidth H + ello


def test_normalize_name_zero_width() -> None:
    """Zero-width characters should be removed."""
    assert normalize_name("he\u200bllo") == "hello"


def test_normalize_name_strip() -> None:
    """Leading/trailing whitespace should be stripped and lowercased."""
    assert normalize_name("  Alice  ") == "alice"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_fake_entity(entity_id: uuid.UUID, name: str, aliases: list[str] | None = None):
    """Create a minimal mock L1Entity."""
    entity = MagicMock()
    entity.id = entity_id
    entity.name = name
    entity.aliases = aliases or []
    return entity


def _make_entity_repo(get_by_external_id_return=None, get_by_id_return=None, create_return=None):
    """Create a mock EntityRepository."""
    repo = AsyncMock()
    repo.get_by_external_id = AsyncMock(return_value=get_by_external_id_return)
    repo.get_by_id = AsyncMock(return_value=get_by_id_return)
    repo.create = AsyncMock(return_value=create_return)
    return repo


def _make_entity_type_resolver(type_id: uuid.UUID):
    """Return an async callable that always returns the given type_id."""

    async def resolver(type_slug: str, workspace_id: uuid.UUID, session) -> uuid.UUID:
        return type_id

    return resolver


# ─── Task 2: Tier 1 — Exact External ID Match ─────────────────────────────────


@pytest.mark.asyncio
async def test_tier1_exact_external_id() -> None:
    """Tier 1: get_by_external_id returns entity → merged (is_new=False)."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    existing = _make_fake_entity(existing_id, "Alice Smith")

    repo = _make_entity_repo(get_by_external_id_return=existing)
    extracted = ExtractedEntity(
        name="Alice S.",
        entity_type="person",
        external_ids={"slack": "U12345"},
    )
    llm = MagicMock()
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=llm,
        entity_index={},
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    assert entity_id == existing_id
    assert is_new is False
    assert decision["tier"] == "exact"
    assert decision["action"] == "merged"
    assert decision["score"] == 1.0


@pytest.mark.asyncio
async def test_tier1_no_match_falls_through() -> None:
    """Tier 1: get_by_external_id returns None → falls through to Tier 2/3/create."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    type_id = uuid.uuid4()
    new_entity_id = uuid.uuid4()
    new_entity = _make_fake_entity(new_entity_id, "Bob")

    repo = _make_entity_repo(get_by_external_id_return=None, create_return=new_entity)
    extracted = ExtractedEntity(
        name="Bob",
        entity_type="person",
        external_ids={"slack": "U99999"},
    )
    llm = MagicMock()
    type_resolver = _make_entity_type_resolver(type_id)

    _entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=llm,
        entity_index={},
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    # Should have fallen through to create
    assert is_new is True
    assert decision["action"] == "created"


# ─── Task 3: Tier 2 — Fuzzy Name / Alias Match ────────────────────────────────


@pytest.mark.asyncio
async def test_tier2_exact_normalized_name() -> None:
    """Tier 2a: normalized name in entity_index → merged."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    # No external IDs → falls through Tier 1
    repo = _make_entity_repo(get_by_external_id_return=None)
    extracted = ExtractedEntity(name="Alice Smith", entity_type="person")
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
    assert decision["action"] == "merged"
    assert decision["score"] == 1.0


@pytest.mark.asyncio
async def test_tier2_alias_match() -> None:
    """Tier 2a: normalized alias in alias_index → merged_via_alias."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()

    repo = _make_entity_repo(get_by_external_id_return=None)
    extracted = ExtractedEntity(name="A. Smith", entity_type="person")
    # "a. smith" normalized matches an alias
    alias_index = {"a. smith": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=MagicMock(),
        entity_index={},
        alias_index=alias_index,
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    assert entity_id == existing_id
    assert is_new is False
    assert decision["tier"] == "fuzzy"
    assert decision["action"] == "merged_via_alias"
    assert decision["score"] == 1.0


@pytest.mark.asyncio
async def test_tier2_jaro_winkler_high() -> None:
    """Tier 2b: Jaro-Winkler score >= 0.92 → auto-merge."""
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
async def test_tier2_jaro_winkler_low() -> None:
    """Tier 2b: score < 0.85 → create new entity."""
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    new_entity_id = uuid.uuid4()
    new_entity = _make_fake_entity(new_entity_id, "Zebra")

    repo = _make_entity_repo(get_by_external_id_return=None, create_return=new_entity)
    # Very different names → low JW score
    extracted = ExtractedEntity(name="Zebra", entity_type="animal")
    entity_index = {"alice smith": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())

    _entity_id, is_new, decision = await resolve_entity(
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

    assert is_new is True
    assert decision["action"] == "created"


# ─── Task 4: Tier 3 — LLM Fallback ───────────────────────────────────────────


def _make_llm_with_response(is_same: bool) -> FakeLLMAdapter:
    """Create a FakeLLMAdapter that always returns a fixed EntityMatchResult."""
    from alayaos_core.llm.interface import LLMUsage

    llm = FakeLLMAdapter()
    original_extract = llm.extract

    async def patched_extract(
        text, system_prompt, response_model, *, max_tokens=4096, temperature=0.0, stage="unknown"
    ):
        if response_model is EntityMatchResult:
            usage = LLMUsage(tokens_in=10, tokens_out=5, tokens_cached=0, cost_usd=0.0)
            return EntityMatchResult(is_same_entity=is_same, reasoning="test"), usage
        return await original_extract(
            text, system_prompt, response_model, max_tokens=max_tokens, temperature=temperature
        )

    llm.extract = patched_extract
    return llm


@pytest.mark.asyncio
async def test_tier3_llm_accepts() -> None:
    """Tier 3: score in [0.85, 0.92), LLM says same entity → merged.

    Uses "johnathan" vs "jonathan" (JW ~0.90) which is in the ambiguous band.
    """
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    existing = _make_fake_entity(existing_id, "jonathan")

    repo = _make_entity_repo(get_by_external_id_return=None, get_by_id_return=existing)
    # JaroWinkler("johnathan", "jonathan") ≈ 0.9037 — in [0.85, 0.92) band
    extracted = ExtractedEntity(name="johnathan", entity_type="person")
    entity_index = {"jonathan": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())
    llm = _make_llm_with_response(is_same=True)

    entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=llm,
        entity_index=entity_index,
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    assert entity_id == existing_id
    assert is_new is False
    assert decision["tier"] == "llm"
    assert decision["action"] == "merged"


@pytest.mark.asyncio
async def test_tier3_llm_rejects() -> None:
    """Tier 3: score in [0.85, 0.92), LLM says different → create new.

    Uses "johnathan" vs "jonathan" (JW ~0.90) which is in the ambiguous band.
    """
    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    new_entity_id = uuid.uuid4()
    existing = _make_fake_entity(existing_id, "jonathan")
    new_entity = _make_fake_entity(new_entity_id, "johnathan")

    repo = _make_entity_repo(
        get_by_external_id_return=None,
        get_by_id_return=existing,
        create_return=new_entity,
    )
    extracted = ExtractedEntity(name="johnathan", entity_type="person")
    entity_index = {"jonathan": existing_id}
    type_resolver = _make_entity_type_resolver(uuid.uuid4())
    llm = _make_llm_with_response(is_same=False)

    _entity_id, is_new, decision = await resolve_entity(
        extracted=extracted,
        workspace_id=ws_id,
        run_id=run_id,
        session=MagicMock(),
        llm=llm,
        entity_index=entity_index,
        alias_index={},
        entity_repo=repo,
        entity_type_resolver=type_resolver,
    )

    assert is_new is True
    assert decision["tier"] == "llm"
    assert decision["action"] == "rejected"


# ─── Task 5: Resolve Batch ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_batch() -> None:
    """End-to-end resolve_batch with multiple entities."""
    from alayaos_core.extraction.resolver import resolve_batch

    ws_id = uuid.uuid4()
    run_id = uuid.uuid4()

    existing_id = uuid.uuid4()
    new_entity_id = uuid.uuid4()
    existing_entity = _make_fake_entity(existing_id, "Alice Smith")
    existing_entity.aliases = []
    new_entity = _make_fake_entity(new_entity_id, "Bob Jones")

    repo = AsyncMock()
    # list() returns existing entities for building indexes
    repo.list = AsyncMock(return_value=([existing_entity], None, False))
    repo.get_by_external_id = AsyncMock(return_value=None)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=new_entity)

    extracted_entities = [
        # Exact normalized name match → merged
        ExtractedEntity(name="Alice Smith", entity_type="person"),
        # New entity → created
        ExtractedEntity(name="Bob Jones", entity_type="person"),
    ]

    type_id = uuid.uuid4()

    async def fake_type_resolver(type_slug, workspace_id, session):
        return type_id

    # Patch resolve_entity_type_id in resolve_batch via the module
    import alayaos_core.extraction.resolver as resolver_mod

    original = resolver_mod.resolve_entity_type_id
    resolver_mod.resolve_entity_type_id = fake_type_resolver

    try:
        entity_name_to_id, decisions = await resolve_batch(
            extracted_entities=extracted_entities,
            workspace_id=ws_id,
            run_id=run_id,
            session=MagicMock(),
            llm=MagicMock(),
            entity_repo=repo,
        )
    finally:
        resolver_mod.resolve_entity_type_id = original

    assert len(decisions) == 2
    assert entity_name_to_id["Alice Smith"] == existing_id
    assert entity_name_to_id["Bob Jones"] == new_entity_id

    # Check decision audit fields
    alice_decision = next(d for d in decisions if d["entity_name"] == "Alice Smith")
    assert alice_decision["action"] == "merged"
    assert alice_decision["is_new"] is False

    bob_decision = next(d for d in decisions if d["entity_name"] == "Bob Jones")
    assert bob_decision["action"] == "created"
    assert bob_decision["is_new"] is True


# ─── Task 6 extra: resolve_entity_type_id fallback ────────────────────────────


@pytest.mark.asyncio
async def test_resolve_entity_type_fallback() -> None:
    """Unknown entity type slug → falls back to 'topic' type."""
    ws_id = uuid.uuid4()
    topic_id = uuid.uuid4()

    topic_et = MagicMock()
    topic_et.id = topic_id

    # Mock EntityTypeRepository: get_by_slug("unknown") → None, get_by_slug("topic") → topic_et
    with MagicMock() as mock_session:
        from unittest.mock import patch

        mock_repo = AsyncMock()
        mock_repo.get_by_slug = AsyncMock(side_effect=lambda workspace_id, slug: None if slug != "topic" else topic_et)

        with patch("alayaos_core.extraction.resolver.EntityTypeRepository", return_value=mock_repo):
            result = await resolve_entity_type_id("unknown_type", ws_id, mock_session)

    assert result == topic_id
