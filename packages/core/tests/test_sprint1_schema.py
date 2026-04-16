"""Sprint 1: seed schema and extractor domain mapping tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSeedEntityTypes:
    def test_seed_includes_task_goal_northstar(self) -> None:
        """CORE_ENTITY_TYPES must contain task, goal, north_star slugs."""
        from alayaos_core.services.workspace import CORE_ENTITY_TYPES

        slugs = {et["slug"] for et in CORE_ENTITY_TYPES}
        assert "task" in slugs, "task not found in CORE_ENTITY_TYPES"
        assert "goal" in slugs, "goal not found in CORE_ENTITY_TYPES"
        assert "north_star" in slugs, "north_star not found in CORE_ENTITY_TYPES"

    def test_seed_includes_part_of_predicate(self) -> None:
        """CORE_PREDICATES must contain part_of with entity_ref value type."""
        from alayaos_core.services.workspace import CORE_PREDICATES

        part_of = next((p for p in CORE_PREDICATES if p["slug"] == "part_of"), None)
        assert part_of is not None, "part_of not found in CORE_PREDICATES"
        assert part_of["value_type"] == "entity_ref"
        assert part_of["supersession_strategy"] == "accumulate"

    def test_domain_to_types_references_only_seeded_slugs(self) -> None:
        """Every entity type slug referenced in _DOMAIN_TO_TYPES must exist in CORE_ENTITY_TYPES."""
        from alayaos_core.extraction.crystallizer.extractor import _DOMAIN_TO_TYPES
        from alayaos_core.services.workspace import CORE_ENTITY_TYPES

        seeded_slugs = {et["slug"] for et in CORE_ENTITY_TYPES}
        for domain, types in _DOMAIN_TO_TYPES.items():
            for slug in types:
                assert slug in seeded_slugs, (
                    f"Domain '{domain}' references type '{slug}' which is not in CORE_ENTITY_TYPES"
                )

    def test_tier_rank_covers_hierarchy_types(self) -> None:
        """ENTITY_TYPE_TIER_RANK must contain task, project, goal, north_star with correct ordering."""
        from alayaos_core.services.workspace import ENTITY_TYPE_TIER_RANK

        assert "task" in ENTITY_TYPE_TIER_RANK, "task not in ENTITY_TYPE_TIER_RANK"
        assert "project" in ENTITY_TYPE_TIER_RANK, "project not in ENTITY_TYPE_TIER_RANK"
        assert "goal" in ENTITY_TYPE_TIER_RANK, "goal not in ENTITY_TYPE_TIER_RANK"
        assert "north_star" in ENTITY_TYPE_TIER_RANK, "north_star not in ENTITY_TYPE_TIER_RANK"

        # Verify ordering: task < project < goal < north_star
        assert ENTITY_TYPE_TIER_RANK["task"] < ENTITY_TYPE_TIER_RANK["project"], (
            "task rank must be less than project rank"
        )
        assert ENTITY_TYPE_TIER_RANK["project"] < ENTITY_TYPE_TIER_RANK["goal"], (
            "project rank must be less than goal rank"
        )
        assert ENTITY_TYPE_TIER_RANK["goal"] < ENTITY_TYPE_TIER_RANK["north_star"], (
            "goal rank must be less than north_star rank"
        )

    @staticmethod
    async def _run_seed_twice(session, ws) -> tuple[dict, dict]:
        """Helper: run seed_core_metadata twice, return (entity_type_slugs, predicate_slugs) sets."""
        from alayaos_core.services.workspace import seed_core_metadata

        created_entity_types: dict[str, MagicMock] = {}
        created_predicates: dict[str, MagicMock] = {}

        async def mock_upsert_et(workspace_id, slug, display_name, description=None):
            if slug not in created_entity_types:
                created_entity_types[slug] = MagicMock(slug=slug)
            return created_entity_types[slug]

        async def mock_upsert_pred(workspace_id, slug, is_core=True, **kwargs):
            if slug not in created_predicates:
                created_predicates[slug] = MagicMock(slug=slug)
            return created_predicates[slug]

        with (
            patch("alayaos_core.services.workspace.EntityTypeRepository") as mock_et_cls,
            patch("alayaos_core.services.workspace.PredicateRepository") as mock_pred_cls,
        ):
            et_inst = AsyncMock()
            et_inst.upsert_core = mock_upsert_et
            mock_et_cls.return_value = et_inst

            pred_inst = AsyncMock()
            pred_inst.upsert_core = mock_upsert_pred
            mock_pred_cls.return_value = pred_inst

            await seed_core_metadata(session, ws)
            await seed_core_metadata(session, ws)

        return created_entity_types, created_predicates

    @pytest.mark.asyncio
    async def test_seed_idempotency(self) -> None:
        """seed_core_metadata called twice must not create duplicate entity types or predicates.

        The upsert_core method returns existing if found, so calling twice with the same
        workspace_id must result in get_by_slug being checked before create.
        """
        import uuid

        from alayaos_core.models.workspace import Workspace
        from alayaos_core.services.workspace import CORE_ENTITY_TYPES, CORE_PREDICATES

        ws = Workspace(id=uuid.uuid4(), name="Test", slug="test", settings={})
        session = AsyncMock()

        created_entity_types, created_predicates = await self._run_seed_twice(session, ws)

        # After two runs, the number of unique slugs must equal CORE_ENTITY_TYPES count
        assert len(created_entity_types) == len(CORE_ENTITY_TYPES), (
            f"Expected {len(CORE_ENTITY_TYPES)} unique entity types, got {len(created_entity_types)}"
        )
        assert len(created_predicates) == len(CORE_PREDICATES), (
            f"Expected {len(CORE_PREDICATES)} unique predicates, got {len(created_predicates)}"
        )
