"""PanoramicPass — holistic knowledge graph triage pass.

Reviews all entities in a workspace and proposes structural actions:
remove_noise, reclassify, rewrite, create_from_cluster, link_cross_type.

This pass does NOT merge entities (dedup is a separate pass).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel, Field

from alayaos_core.extraction.integrator.normalization import normalize_for_hint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alayaos_core.extraction.integrator.schemas import EntityWithContext

log = structlog.get_logger()

# Default maximum entity count before applying the scalability cap.
# Can be overridden via the PanoramicPass constructor.
_DEFAULT_MAX_ENTITIES = 500

# Pre-compiled regexes for deterministic garbage detection (before LLM call).
_RE_HEX_ID = re.compile(r"^[0-9a-f]{16,}$")
_RE_SLACK_HANDLE = re.compile(r"^U[A-Z0-9]{8,}$")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PanoramicAction(BaseModel):
    """A single proposed action from the panoramic triage pass."""

    action: Literal["remove_noise", "reclassify", "rewrite", "create_from_cluster", "link_cross_type"]
    entity_id: uuid.UUID | None = None
    params: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=280)


class PanoramicResult(BaseModel):
    """Result of a panoramic triage pass — list of proposed actions."""

    actions: list[PanoramicAction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _is_garbage(name: str) -> bool:
    """Deterministic pre-filter: returns True if the name looks like a system artifact."""
    return bool(_RE_HEX_ID.match(name)) or bool(_RE_SLACK_HANDLE.match(name))


def _build_entity_table(
    entities: list[EntityWithContext],
    claims_by_entity: dict[uuid.UUID, list[dict]],
    relations_by_entity: dict[uuid.UUID, list[dict]],
) -> str:
    """Serialise entities to a compact text table for the LLM prompt."""
    lines: list[str] = []
    for e in entities:
        hint = normalize_for_hint(e.name)
        garbage_hint = _is_garbage(e.name)
        top_claims = (claims_by_entity.get(e.id) or [])[:3]
        top_relations = (relations_by_entity.get(e.id) or [])[:3]
        line = (
            f"id={e.id} name={e.name!r} type={e.entity_type}"
            f" aliases={e.aliases}"
            f" garbage_hint={garbage_hint}"
            f" hints={hint}"
        )
        if top_claims:
            line += f" claims={top_claims}"
        if top_relations:
            line += f" relations={top_relations}"
        lines.append(line)
    return "\n".join(lines)


# Prompt template — Cyrillic examples replaced with transliterated equivalents.
_SYSTEM_PROMPT = """You are a knowledge graph curator for a corporate workspace.

## Your task
Review ALL entities below. For each, decide what actions are needed to clean and structure the graph.

## Entity types (with tier rank for work hierarchy)
- task (tier 1): daily/weekly work items
- project (tier 2): 1 week to 1 month initiatives
- goal (tier 3): monthly/quarterly objectives
- north_star (tier 4): yearly to multi-year strategic objectives
- person, team, document, decision, meeting, topic, tool, process, event (no tier)

## Available actions
1. remove_noise(entity_id, reason) — garbage: hex IDs, unresolved handles, generic nouns
2. reclassify(entity_id, from_type, to_type, reason) — wrong entity type
3. rewrite(entity_id, new_name, new_description) — long name -> short name + description
4. create_from_cluster(child_ids, entity_type, name, description) — create parent + part_of links
5. link_cross_type(source_id, target_id, relation_type) — connect related entities of different types

## Rules
- NEVER merge entities here (dedup is a separate pass)
- create_from_cluster: only when >=3 children, shared structural signal (owner/time/topic)
- create_from_cluster: parent tier_rank > children tier_rank (task -> project, project -> goal)
- reclassify: only when confident (MTS=company not person, Serdce=song not event)
- rewrite: split names longer than ~50 chars into short_name + description
- link_cross_type: when entities clearly reference the same real-world thing

## Current date
{current_date}

## Entities ({count} total)
{entity_table}"""


# ---------------------------------------------------------------------------
# PanoramicPass
# ---------------------------------------------------------------------------


class PanoramicPass:
    """Holistic triage pass: reviews all entities and proposes structural actions.

    Workflow:
    1. Apply deterministic garbage pre-filter (hex IDs, Slack handles).
    2. Enforce scalability cap if entity count exceeds max_entities.
    3. Call LLM with the full entity table.
    4. Validate LLM response via PanoramicResult Pydantic schema.
    5. Filter out actions referencing non-existent entity UUIDs.
    6. Return PanoramicResult.
    """

    def __init__(
        self,
        llm_service,  # LLMServiceInterface
        session: AsyncSession,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
    ) -> None:
        self._llm = llm_service
        self._session = session
        self._max_entities = max_entities

    async def run(
        self,
        workspace_id: uuid.UUID,
        entities: list[EntityWithContext],
        entity_types: list,
        claims_by_entity: dict[uuid.UUID, list[dict]],
        relations_by_entity: dict[uuid.UUID, list[dict]],
    ) -> PanoramicResult:
        """Execute the panoramic triage pass for a workspace."""
        if not entities:
            return PanoramicResult()

        # Scalability cap: if entity count exceeds threshold, warn and trim to cap
        if len(entities) > self._max_entities:
            log.warning(
                "panoramic_pass_entity_cap_exceeded",
                workspace_id=str(workspace_id),
                entity_count=len(entities),
                max_entities=self._max_entities,
                msg="Applying panoramic max-entity cap; processing subset only",
            )
            # Keep the head of the list as the priority window
            entities = entities[: self._max_entities]

        # Build valid entity ID set for UUID validation after LLM call
        valid_ids: set[uuid.UUID] = {e.id for e in entities}

        # Build entity table for prompt
        entity_table = _build_entity_table(entities, claims_by_entity, relations_by_entity)

        prompt_text = f"Workspace entities for triage:\n{entity_table}"
        system_prompt = _SYSTEM_PROMPT.format(
            current_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            count=len(entities),
            entity_table=entity_table,
        )

        # Call LLM — output is untrusted; validate via PanoramicResult Pydantic schema
        try:
            result, _usage = await self._llm.extract(
                text=prompt_text,
                system_prompt=system_prompt,
                response_model=PanoramicResult,
                max_tokens=4096,
            )
        except Exception:
            log.warning("panoramic_pass_llm_failed", workspace_id=str(workspace_id))
            return PanoramicResult()

        # Validate entity_ids: drop actions referencing unknown UUIDs
        # Fix 1: single-entity actions (remove_noise, reclassify, rewrite) MUST have entity_id
        single_entity_actions = {"remove_noise", "reclassify", "rewrite"}
        validated_actions: list[PanoramicAction] = []
        for action in result.actions:
            if action.entity_id is not None and action.entity_id not in valid_ids:
                log.warning(
                    "panoramic_pass_unknown_entity_id",
                    workspace_id=str(workspace_id),
                    action=action.action,
                    entity_id=str(action.entity_id),
                )
                continue

            # Fix 1: single-entity actions without entity_id are invalid
            if action.action in single_entity_actions and action.entity_id is None:
                log.warning(
                    "panoramic_pass_missing_entity_id",
                    workspace_id=str(workspace_id),
                    action=action.action,
                )
                continue

            # Fix 2: validate params-level entity references
            if action.action == "create_from_cluster":
                child_ids_raw: list[str] = action.params.get("child_ids", [])
                invalid_children = []
                for cid in child_ids_raw:
                    try:
                        parsed = uuid.UUID(str(cid))
                    except (ValueError, AttributeError):
                        invalid_children.append(cid)
                        continue
                    if parsed not in valid_ids:
                        invalid_children.append(cid)
                if invalid_children:
                    log.warning(
                        "panoramic_pass_invalid_child_ids",
                        workspace_id=str(workspace_id),
                        invalid_ids=invalid_children,
                    )
                    continue

            if action.action == "link_cross_type":
                source_raw = action.params.get("source_id")
                target_raw = action.params.get("target_id")
                invalid_ref = None
                for ref_name, ref_val in (("source_id", source_raw), ("target_id", target_raw)):
                    if ref_val is not None:
                        try:
                            parsed_ref = uuid.UUID(str(ref_val))
                        except (ValueError, AttributeError):
                            invalid_ref = ref_name
                            break
                        if parsed_ref not in valid_ids:
                            invalid_ref = ref_name
                            break
                if invalid_ref is not None:
                    log.warning(
                        "panoramic_pass_invalid_params_ref",
                        workspace_id=str(workspace_id),
                        action=action.action,
                        invalid_param=invalid_ref,
                    )
                    continue

            validated_actions.append(action)

        return PanoramicResult(actions=validated_actions)
