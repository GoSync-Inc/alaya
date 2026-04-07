"""Security and correctness regression tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.repositories.workspace import WorkspaceRepository


class TestPatchExcludeUnset:
    @pytest.mark.asyncio
    async def test_patch_with_explicit_null_passes_none(self) -> None:
        """exclude_unset allows setting fields to None explicitly."""
        from alayaos_core.schemas.entity import EntityUpdate

        body = EntityUpdate.model_validate({"description": None})
        dumped = body.model_dump(exclude_unset=True)
        assert "description" in dumped
        assert dumped["description"] is None

    @pytest.mark.asyncio
    async def test_patch_without_field_excludes_it(self) -> None:
        """exclude_unset ignores fields not present in the request."""
        from alayaos_core.schemas.entity import EntityUpdate

        body = EntityUpdate.model_validate({"name": "Updated"})
        dumped = body.model_dump(exclude_unset=True)
        assert "name" in dumped
        assert "description" not in dumped


class TestWorkspaceWhitelist:
    @pytest.mark.asyncio
    async def test_update_rejects_disallowed_fields(self) -> None:
        """WorkspaceRepository.update ignores non-whitelisted fields like id, created_at."""
        from alayaos_core.models.workspace import Workspace

        ws = Workspace(
            id=uuid.uuid4(),
            name="Original",
            slug="original",
            settings={},
        )
        original_id = ws.id

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ws
        session.execute = AsyncMock(return_value=mock_result)

        repo = WorkspaceRepository(session)
        await repo.update(ws.id, id=uuid.uuid4(), name="Changed")

        # id should NOT have changed (disallowed), name should have changed (allowed)
        assert ws.id == original_id
        assert ws.name == "Changed"


class TestLazyRaise:
    def test_entity_type_relationship_is_raise(self) -> None:
        """L1Entity.entity_type must use lazy='raise' to prevent N+1."""
        from alayaos_core.models.entity import L1Entity

        prop = L1Entity.__mapper__.relationships["entity_type"]
        assert prop.lazy == "raise"

    def test_external_id_entity_relationship_is_raise(self) -> None:
        """EntityExternalId.entity must use lazy='raise' to prevent N+1."""
        from alayaos_core.models.entity import EntityExternalId

        prop = EntityExternalId.__mapper__.relationships["entity"]
        assert prop.lazy == "raise"
