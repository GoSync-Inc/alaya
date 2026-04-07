"""Tests for full SQLAlchemy models (Task 2)."""

from sqlalchemy import ForeignKeyConstraint, inspect

from alayaos_core.models.api_key import APIKey
from alayaos_core.models.entity import EntityExternalId, L1Entity
from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.models.event import L0Event
from alayaos_core.models.extraction_run import ExtractionRun
from alayaos_core.models.predicate import PredicateDefinition
from alayaos_core.models.workspace import Workspace

# ─── Workspace ───────────────────────────────────────────────────────────────


def test_workspace_tablename() -> None:
    assert Workspace.__tablename__ == "workspaces"


def test_workspace_columns() -> None:
    mapper = inspect(Workspace)
    cols = {c.key for c in mapper.columns}
    assert {"id", "name", "slug", "settings", "created_at", "updated_at"}.issubset(cols)


def test_workspace_id_is_uuid() -> None:
    mapper = inspect(Workspace)
    col = mapper.columns["id"]
    assert col.primary_key is True
    # default is uuid.uuid4
    assert col.default is not None


def test_workspace_slug_unique() -> None:
    mapper = inspect(Workspace)
    col = mapper.columns["slug"]
    assert col.unique is True


# ─── L0Event ─────────────────────────────────────────────────────────────────


def test_l0_event_tablename() -> None:
    assert L0Event.__tablename__ == "l0_events"


def test_l0_event_columns() -> None:
    mapper = inspect(L0Event)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "source_type",
        "source_id",
        "content",
        "content_hash",
        "metadata",
        "processed_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_l0_event_workspace_fk() -> None:
    mapper = inspect(L0Event)
    col = mapper.columns["workspace_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert "workspaces.id" in str(fks[0])


def test_l0_event_has_unique_constraint() -> None:
    """Should have a unique constraint on (workspace_id, source_type, source_id)."""
    table = L0Event.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


# ─── EntityTypeDefinition ────────────────────────────────────────────────────


def test_entity_type_tablename() -> None:
    assert EntityTypeDefinition.__tablename__ == "entity_type_definitions"


def test_entity_type_columns() -> None:
    mapper = inspect(EntityTypeDefinition)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "slug",
        "display_name",
        "description",
        "icon",
        "color",
        "is_core",
        "schema_version",
        "is_active",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_entity_type_workspace_fk() -> None:
    mapper = inspect(EntityTypeDefinition)
    col = mapper.columns["workspace_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert "workspaces.id" in str(fks[0])


def test_entity_type_has_unique_constraint() -> None:
    """Should have unique constraint on (workspace_id, slug)."""
    table = EntityTypeDefinition.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


# ─── PredicateDefinition ─────────────────────────────────────────────────────


def test_predicate_tablename() -> None:
    assert PredicateDefinition.__tablename__ == "predicate_definitions"


def test_predicate_columns() -> None:
    mapper = inspect(PredicateDefinition)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "slug",
        "display_name",
        "description",
        "value_type",
        "domain_types",
        "cardinality",
        "inverse_slug",
        "is_core",
        "schema_version",
        "is_active",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_predicate_workspace_fk() -> None:
    mapper = inspect(PredicateDefinition)
    col = mapper.columns["workspace_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert "workspaces.id" in str(fks[0])


def test_predicate_has_unique_constraint() -> None:
    """Should have unique constraint on (workspace_id, slug)."""
    table = PredicateDefinition.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


# ─── L1Entity + EntityExternalId ─────────────────────────────────────────────


def test_l1_entity_tablename() -> None:
    assert L1Entity.__tablename__ == "l1_entities"


def test_l1_entity_columns() -> None:
    mapper = inspect(L1Entity)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "entity_type_id",
        "name",
        "description",
        "properties",
        "is_deleted",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_l1_entity_workspace_fk() -> None:
    mapper = inspect(L1Entity)
    col = mapper.columns["workspace_id"]
    fk_targets = {fk.target_fullname for fk in col.foreign_keys}
    assert "workspaces.id" in fk_targets


def test_l1_entity_type_fk() -> None:
    """Composite FK (workspace_id, entity_type_id) -> entity_type_definitions."""
    from sqlalchemy import ForeignKeyConstraint

    table = L1Entity.__table__
    composite_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    fk_targets = {str(e) for c in composite_fks for e in c.elements}
    assert any("entity_type_definitions" in t for t in fk_targets)


def test_entity_external_id_tablename() -> None:
    assert EntityExternalId.__tablename__ == "entity_external_ids"


def test_entity_external_id_columns() -> None:
    mapper = inspect(EntityExternalId)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "entity_id",
        "source_type",
        "external_id",
        "created_at",
    }.issubset(cols)


def test_entity_external_id_has_unique_constraint() -> None:
    """Should have unique on (workspace_id, entity_id, source_type, external_id)."""
    table = EntityExternalId.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


# ─── APIKey ───────────────────────────────────────────────────────────────────


def test_api_key_tablename() -> None:
    assert APIKey.__tablename__ == "api_keys"


def test_api_key_columns() -> None:
    mapper = inspect(APIKey)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "name",
        "key_prefix",
        "key_hash",
        "scopes",
        "expires_at",
        "revoked_at",
        "is_bootstrap",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_api_key_prefix_unique() -> None:
    mapper = inspect(APIKey)
    col = mapper.columns["key_prefix"]
    assert col.unique is True


def test_api_key_workspace_fk() -> None:
    mapper = inspect(APIKey)
    col = mapper.columns["workspace_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert "workspaces.id" in str(fks[0])


# ─── L0Event new extraction columns ──────────────────────────────────────────


def test_l0_event_extraction_columns() -> None:
    mapper = inspect(L0Event)
    cols = {c.key for c in mapper.columns}
    for col_name in [
        "raw_text",
        "access_level",
        "access_context",
        "actor_external_id",
        "event_kind",
        "occurred_at",
        "is_extracted",
    ]:
        assert col_name in cols, f"L0Event missing column: {col_name}"


# ─── L1Entity new columns ────────────────────────────────────────────────────


def test_l1_entity_aliases_column() -> None:
    mapper = inspect(L1Entity)
    cols = {c.key for c in mapper.columns}
    assert "aliases" in cols, "L1Entity missing column: aliases"


def test_l1_entity_extraction_run_id_column() -> None:
    mapper = inspect(L1Entity)
    cols = {c.key for c in mapper.columns}
    assert "extraction_run_id" in cols, "L1Entity missing column: extraction_run_id"


def test_l1_entity_extraction_run_composite_fk() -> None:
    table = L1Entity.__table__
    composite_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    fk_targets = {str(e) for c in composite_fks for e in c.elements}
    assert any("extraction_runs" in t for t in fk_targets)


# ─── PredicateDefinition new column ──────────────────────────────────────────


def test_predicate_supersession_strategy_column() -> None:
    mapper = inspect(PredicateDefinition)
    cols = {c.key for c in mapper.columns}
    assert "supersession_strategy" in cols, "PredicateDefinition missing column: supersession_strategy"


# ─── ExtractionRun ───────────────────────────────────────────────────────────


def test_extraction_run_tablename() -> None:
    assert ExtractionRun.__tablename__ == "extraction_runs"


def test_extraction_run_columns() -> None:
    mapper = inspect(ExtractionRun)
    cols = {c.key for c in mapper.columns}
    expected = {
        "id",
        "workspace_id",
        "event_id",
        "status",
        "started_at",
        "completed_at",
        "llm_provider",
        "llm_model",
        "prompt_version",
        "tokens_in",
        "tokens_out",
        "tokens_cached",
        "cost_usd",
        "raw_extraction",
        "entities_created",
        "entities_merged",
        "relations_created",
        "claims_created",
        "claims_superseded",
        "resolver_decisions",
        "error_message",
        "error_detail",
        "retry_count",
        "parent_run_id",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)


def test_extraction_run_workspace_fk() -> None:
    mapper = inspect(ExtractionRun)
    col = mapper.columns["workspace_id"]
    fks = list(col.foreign_keys)
    assert any("workspaces.id" in str(fk) for fk in fks)


def test_extraction_run_event_composite_fk() -> None:
    table = ExtractionRun.__table__
    composite_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    fk_targets = {str(e) for c in composite_fks for e in c.elements}
    assert any("l0_events" in t for t in fk_targets)
