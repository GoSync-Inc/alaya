"""Run 6.2 S1 Block A model and schema contracts."""

import uuid
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.sql.schema import DefaultClause

from alayaos_core.models.vector import VectorChunk
from alayaos_core.schemas.api_key import APIKeyCreate


def test_vector_chunk_access_level_column_contract() -> None:
    mapper = inspect(VectorChunk)

    col = mapper.columns["access_level"]

    assert str(col.type) == "TEXT"
    assert col.nullable is False
    assert isinstance(col.server_default, DefaultClause)
    assert str(col.server_default.arg) == "restricted"


def test_claim_effective_access_view_model_is_read_only_exported() -> None:
    from alayaos_core import models
    from alayaos_core.models.claim_effective_access import ClaimEffectiveAccess

    mapper = inspect(ClaimEffectiveAccess)

    assert models.ClaimEffectiveAccess is ClaimEffectiveAccess
    assert ClaimEffectiveAccess.__tablename__ == "claim_effective_access"
    assert ClaimEffectiveAccess.__table__.info["read_only"] is True
    assert {col.key for col in mapper.primary_key} == {"workspace_id", "claim_id"}
    assert "max_tier_rank" in mapper.columns
    assert str(mapper.columns["max_tier_rank"].type) == "INTEGER"
    assert mapper.columns["max_tier_rank"].nullable is False


def test_api_key_create_scopes_are_closed_literals() -> None:
    assert APIKeyCreate(name="CI", scopes=["read", "write", "admin"]).scopes == ["read", "write", "admin"]

    with pytest.raises(ValidationError):
        APIKeyCreate(name="CI", scopes=["read", "restricted"])

    assert "allowed_access_levels" not in APIKeyCreate.model_fields


def test_tree_node_view_is_frozen_dataclass_dto() -> None:
    from alayaos_core.schemas.tree import TreeNodeView

    now = datetime.now(tz=UTC)
    view = TreeNodeView(
        id=uuid.uuid4(),
        path="/teams/search",
        workspace_id=uuid.uuid4(),
        entity_id=None,
        node_type="folder",
        is_dirty=False,
        last_rebuilt_at=now,
        markdown_cache="# Search",
        summary=None,
    )

    assert is_dataclass(TreeNodeView)
    assert view.summary is None
    with pytest.raises(FrozenInstanceError):
        view.summary = {"leak": True}  # type: ignore[misc]
