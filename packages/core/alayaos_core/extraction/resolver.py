"""Entity resolution: normalize, match, and create entities from extraction output."""

import unicodedata
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.extraction.schemas import EntityMatchResult, ExtractedEntity
from alayaos_core.repositories.entity import EntityRepository
from alayaos_core.repositories.entity_type import EntityTypeRepository

log = structlog.get_logger()


async def _get_entity_internal(entity_repo: EntityRepository, entity_id: uuid.UUID):
    if hasattr(type(entity_repo), "get_by_id_unfiltered"):
        return await entity_repo.get_by_id_unfiltered(entity_id)
    return await entity_repo.get_by_id(entity_id)


async def _list_entities_internal(
    entity_repo: EntityRepository,
    *,
    limit: int,
    cursor: str | None,
):
    if hasattr(type(entity_repo), "list_unfiltered"):
        return await entity_repo.list_unfiltered(limit=limit, cursor=cursor)
    return await entity_repo.list(limit=limit, cursor=cursor)


def normalize_name(name: str) -> str:
    """NFKC + lowercase + strip + zero-width removal."""
    name = unicodedata.normalize("NFKC", name)
    name = name.strip().lower()
    # Remove zero-width characters (Unicode category Cf = format characters)
    name = "".join(c for c in name if not unicodedata.category(c).startswith("Cf"))
    return name


def transliterate_name(name: str) -> str:
    """Transliterate between Cyrillic↔Latin for cross-script matching."""
    try:
        from transliterate import translit

        # Try Cyrillic→Latin
        latin = translit(name, "ru", reversed=True)
        return normalize_name(latin)
    except Exception:
        return normalize_name(name)


async def resolve_entity(
    extracted: ExtractedEntity,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: AsyncSession,
    llm,  # LLMServiceInterface
    entity_index: dict[str, uuid.UUID],  # normalized_name → entity_id
    alias_index: dict[str, uuid.UUID],  # normalized_alias → entity_id
    entity_repo: EntityRepository,
    entity_type_resolver: Callable[..., Awaitable[uuid.UUID]],
) -> tuple[uuid.UUID, bool, dict]:
    """Resolve extracted entity to existing or new entity.

    Returns (entity_id, is_new, resolution_decision).
    """
    # Tier 1: Exact external_id match
    for source_type, ext_id in extracted.external_ids.items():
        entity = await entity_repo.get_by_external_id(workspace_id, source_type, ext_id)
        if entity:
            return (
                entity.id,
                False,
                {
                    "tier": "exact",
                    "action": "merged",
                    "score": 1.0,
                    "matched_entity_id": str(entity.id),
                },
            )

    # Tier 2: Fuzzy name + alias match
    from rapidfuzz.distance import JaroWinkler  # deferred import to avoid top-level cost

    normalized = normalize_name(extracted.name)

    # 2a: Exact normalized name match
    if normalized in entity_index:
        return (
            entity_index[normalized],
            False,
            {
                "tier": "fuzzy",
                "action": "merged",
                "score": 1.0,
                "matched_entity_id": str(entity_index[normalized]),
            },
        )
    if normalized in alias_index:
        return (
            alias_index[normalized],
            False,
            {
                "tier": "fuzzy",
                "action": "merged_via_alias",
                "score": 1.0,
                "matched_entity_id": str(alias_index[normalized]),
            },
        )

    # 2b: Jaro-Winkler fuzzy match against all known entities
    # JaroWinkler.normalized_similarity returns 0.0-1.0
    # Skip fuzzy for very short names (< 4 chars) — too unreliable
    best_score = 0.0
    best_id: uuid.UUID | None = None
    if len(normalized) >= 4:
        translit_normalized = transliterate_name(extracted.name)
        for name, eid in entity_index.items():
            # Compare both directions: extracted→indexed and indexed→extracted
            name_translit = transliterate_name(name) if name != normalized else name
            score = max(
                JaroWinkler.normalized_similarity(normalized, name),
                JaroWinkler.normalized_similarity(translit_normalized, name),
                JaroWinkler.normalized_similarity(normalized, name_translit),
            )
            if score > best_score:
                best_score, best_id = score, eid
        # Also check aliases
        for alias, eid in alias_index.items():
            alias_translit = transliterate_name(alias) if alias != normalized else alias
            score = max(
                JaroWinkler.normalized_similarity(normalized, alias),
                JaroWinkler.normalized_similarity(translit_normalized, alias),
                JaroWinkler.normalized_similarity(normalized, alias_translit),
            )
            if score > best_score:
                best_score, best_id = score, eid

    if best_score >= 0.92:
        return (
            best_id,  # type: ignore[return-value]
            False,
            {
                "tier": "fuzzy",
                "action": "merged",
                "score": best_score,
                "matched_entity_id": str(best_id),
            },
        )

    # Tier 3: LLM fallback for ambiguous band (0.85 <= score < 0.92)
    if best_score >= 0.85 and best_id is not None:
        existing_entity = await _get_entity_internal(entity_repo, best_id)
        if existing_entity:
            is_same = await _llm_resolve_entity(llm, extracted, existing_entity)
            if is_same:
                return (
                    best_id,
                    False,
                    {
                        "tier": "llm",
                        "action": "merged",
                        "score": best_score,
                        "matched_entity_id": str(best_id),
                    },
                )
            else:
                log.info(
                    "llm_rejected_merge",
                    extracted_name=extracted.name,
                    candidate_id=str(best_id),
                    score=best_score,
                )
                # Fall through to create, but record the LLM rejection in the decision
                entity_type_id = await entity_type_resolver(extracted.entity_type, workspace_id, session)
                new_entity = await entity_repo.create(
                    workspace_id=workspace_id,
                    entity_type_id=entity_type_id,
                    name=extracted.name,
                    aliases=extracted.aliases,
                    extraction_run_id=run_id,
                )
                entity_index[normalized] = new_entity.id
                for alias in extracted.aliases:
                    alias_index[normalize_name(alias)] = new_entity.id
                for source_type, ext_id in extracted.external_ids.items():
                    await entity_repo.create_external_id(workspace_id, new_entity.id, source_type, ext_id)
                return (
                    new_entity.id,
                    True,
                    {
                        "tier": "llm",
                        "action": "rejected",
                        "score": best_score,
                        "candidate_entity_id": str(best_id),
                    },
                )

    # Create new entity (no fuzzy match found at all)
    entity_type_id = await entity_type_resolver(extracted.entity_type, workspace_id, session)
    new_entity = await entity_repo.create(
        workspace_id=workspace_id,
        entity_type_id=entity_type_id,
        name=extracted.name,
        aliases=extracted.aliases,
        extraction_run_id=run_id,
    )
    # Update in-memory indexes
    entity_index[normalized] = new_entity.id
    for alias in extracted.aliases:
        alias_index[normalize_name(alias)] = new_entity.id

    # Persist external IDs if any
    for source_type, ext_id in extracted.external_ids.items():
        await entity_repo.create_external_id(workspace_id, new_entity.id, source_type, ext_id)

    return new_entity.id, True, {"tier": "none", "action": "created", "score": 0.0}


async def _llm_resolve_entity(llm, extracted: ExtractedEntity, existing) -> bool:
    """Ask LLM: are these the same entity?"""
    prompt = (
        f"Are these the same entity?\n"
        f'Entity A: name="{extracted.name}", type="{extracted.entity_type}", aliases={extracted.aliases}\n'
        f'Entity B: name="{existing.name}", aliases={getattr(existing, "aliases", []) or []}\n'
        f"Respond with is_same_entity (true/false) and brief reasoning."
    )
    result, _ = await llm.extract(
        text=prompt,
        system_prompt="You are an entity resolution assistant. Decide if two entity mentions refer to the same real-world entity.",
        response_model=EntityMatchResult,
        max_tokens=256,
    )
    return result.is_same_entity


async def resolve_entity_type_id(
    type_slug: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
) -> uuid.UUID:
    """Resolve entity type slug to UUID. Falls back to 'topic' for unknown types."""
    repo = EntityTypeRepository(session)
    et = await repo.get_by_slug(workspace_id, type_slug)
    if et:
        return et.id
    # Fallback to 'topic' for unknown entity types
    fallback = await repo.get_by_slug(workspace_id, "topic")
    if fallback:
        return fallback.id
    raise ValueError(f"Entity type '{type_slug}' not found and no fallback available")


async def resolve_batch(
    extracted_entities: list[ExtractedEntity],
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: AsyncSession,
    llm,
    entity_repo: EntityRepository,
) -> tuple[dict[str, uuid.UUID], list[dict]]:
    """Resolve a batch of extracted entities.

    Returns:
        - entity_name_to_id: mapping of entity names to resolved IDs
        - resolver_decisions: list of resolution decision dicts for each entity
    """
    # Build in-memory indexes from existing entities
    entity_index: dict[str, uuid.UUID] = {}
    alias_index: dict[str, uuid.UUID] = {}

    # Load ALL existing entities for this workspace (paginate through all)
    cursor = None
    while True:
        batch, next_cursor, has_more = await _list_entities_internal(entity_repo, limit=200, cursor=cursor)
        for entity in batch:
            entity_index[normalize_name(entity.name)] = entity.id
            for alias in entity.aliases or []:
                alias_index[normalize_name(alias)] = entity.id
        if not has_more:
            break
        cursor = next_cursor

    entity_name_to_id: dict[str, uuid.UUID] = {}
    resolver_decisions: list[dict] = []

    for extracted in extracted_entities:
        entity_id, is_new, decision = await resolve_entity(
            extracted=extracted,
            workspace_id=workspace_id,
            run_id=run_id,
            session=session,
            llm=llm,
            entity_index=entity_index,
            alias_index=alias_index,
            entity_repo=entity_repo,
            entity_type_resolver=resolve_entity_type_id,
        )
        decision["entity_name"] = extracted.name
        decision["entity_id"] = str(entity_id)
        decision["is_new"] = is_new
        resolver_decisions.append(decision)
        entity_name_to_id[extracted.name] = entity_id

    return entity_name_to_id, resolver_decisions
